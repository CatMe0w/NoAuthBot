package noauthbot.harness;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

final class RenderCommand {

    private record Entry(SdfReader.Record record, String variant, long seed, String key) {
    }

    private final RenderOptions options;
    private final CidList wanted;
    private final Path runs;
    private final String run;
    private final Map<String, String> versionInfo;
    private final ExecutorService renderers;
    private final Semaphore inFlight;

    private final AtomicLong samples = new AtomicLong();
    private final AtomicLong failed = new AtomicLong();
    private final AtomicLong skippedShards = new AtomicLong();
    private final List<String> errors = Collections.synchronizedList(new ArrayList<>());
    private final List<Future<?>> shardTasks = Collections.synchronizedList(new ArrayList<>());

    RenderCommand(Args args) throws Exception {
        options = RenderOptions.parse(args);
        wanted = CidList.read(options.cids());
        runs = options.out().resolve("_runs");
        run = Io.timestamp() + "-part" + options.part().index();
        versionInfo = Provenance.versionInfo();
        renderers = Io.threadPool(options.threads(), "render");
        inFlight = new Semaphore(options.threads() * 2);
    }

    void run() throws Exception {
        Files.createDirectories(runs);
        Sample.prewarm();
        writeManifest();
        long started = System.nanoTime();
        readOwnedFiles();
        for (Future<?> task : new ArrayList<>(shardTasks)) task.get();
        renderers.shutdown();
        renderers.awaitTermination(1, TimeUnit.MINUTES);
        report((System.nanoTime() - started) / 1e9);
    }

    private void writeManifest() throws IOException {
        Json manifest = new Json().beginObject()
                .key("started").value(Instant.now().toString())
                .key("seed").value(options.seed())
                .key("star_ratio").value(options.starRatio())
                .key("shard_size").value(options.shardSize())
                .key("prefix").value(options.prefix())
                .key("png").value("gray level " + options.pngLevel() + " filter " + options.pngFilterName())
                .key("zstd").value(options.zstdLevel())
                .key("part").value(options.part().toString())
                .key("cid_entries").value(wanted.totalEntries());
        Provenance.write(manifest, versionInfo);
        manifest.key("sdf").beginArray();
        for (Path sdf : options.sdfs()) manifest.value(sdf.getFileName().toString());
        manifest.endArray().endObject();
        Io.atomicWrite(runs.resolve(run + ".json"), manifest.toString());
    }

    private void readOwnedFiles() throws Exception {
        ExecutorService readers = Io.threadPool(options.readers(), "read");
        List<Future<?>> reads = new ArrayList<>();
        List<Path> sdfs = options.sdfs();
        for (int fileIndex = 0; fileIndex < sdfs.size(); fileIndex++) {
            if (!options.part().ownsFile(fileIndex)) continue;
            Path sdf = sdfs.get(fileIndex);
            reads.add(readers.submit(() -> {
                readSdf(sdf);
                return null;
            }));
        }
        for (Future<?> read : reads) read.get();
        readers.shutdown();
    }

    private void readSdf(Path sdf) throws Exception {
        Chunker chunker = new Chunker(Io.sdfStem(sdf));
        try (SdfReader reader = new SdfReader(sdf)) {
            SdfReader.Record record;
            while ((record = reader.next(wanted::contains)) != null) {
                for (Entry entry : entries(record)) chunker.add(entry);
            }
        }
        chunker.finish();
    }

    private List<Entry> entries(SdfReader.Record record) {
        int index = wanted.indexOf(record.cid);
        wanted.markSeen(index);
        int occurrences = wanted.entries(index);
        List<Entry> entries = new ArrayList<>(occurrences);
        for (int occurrence = 0; occurrence < occurrences; occurrence++) {
            entries.add(entry(record, wanted.variant(index, occurrence), occurrence));
        }
        return entries;
    }

    private Entry entry(SdfReader.Record record, String listedVariant, int occurrence) {
        long sampleSeed = Seeds.forSample(options.seed(), record.cid, occurrence);
        String variant = listedVariant != null ? listedVariant
                : Seeds.unitInterval(sampleSeed) < options.starRatio() ? Sample.VARIANT_STAR : Sample.VARIANT_PLAIN;
        String key = record.cid + "_" + (variant.equals(Sample.VARIANT_STAR) ? "s" : "p") + "_" + occurrence;
        return new Entry(record, variant, sampleSeed, key);
    }

    private final class Chunker {
        private final String stem;
        private int index = 0;
        private List<Entry> chunk = new ArrayList<>(options.shardSize());

        Chunker(String stem) {
            this.stem = stem;
        }

        void add(Entry entry) throws InterruptedException {
            chunk.add(entry);
            if (chunk.size() < options.shardSize()) return;
            submitIfOwned();
            index++;
            chunk = new ArrayList<>(options.shardSize());
        }

        void finish() throws InterruptedException {
            if (!chunk.isEmpty()) submitIfOwned();
        }

        private void submitIfOwned() throws InterruptedException {
            if (options.part().ownsChunk(index)) submitShard(stem, index, chunk);
        }
    }

    private void submitShard(String stem, int chunkIndex, List<Entry> chunk) throws InterruptedException {
        String name = String.format("%s-%s-%05d", options.prefix(), stem, chunkIndex);
        Path destination = options.out().resolve(name + options.shardExtension());
        if (Files.exists(destination)) {
            skippedShards.incrementAndGet();
            return;
        }
        inFlight.acquire();
        shardTasks.add(renderers.submit(() -> {
            try {
                writeShard(chunk, options.out().resolve(name + options.shardExtension() + ".tmp"), destination);
            } finally {
                inFlight.release();
            }
            return null;
        }));
    }

    private void writeShard(List<Entry> chunk, Path partial, Path destination) throws IOException {
        int rendered = 0;
        try (TarWriter tar = new TarWriter(partial, options.zstdLevel())) {
            for (Entry entry : chunk) {
                if (addSample(tar, entry)) rendered++;
            }
        }
        Files.move(partial, destination, StandardCopyOption.ATOMIC_MOVE);
        samples.addAndGet(rendered);
    }

    private boolean addSample(TarWriter tar, Entry entry) {
        try {
            Sample sample = Sample.render(entry.record(), entry.variant(), entry.seed(), entry.key(),
                    versionInfo, options.pngLevel(), options.pngFilter());
            tar.add(entry.key() + ".png", sample.png);
            tar.add(entry.key() + ".json", sample.json.getBytes(StandardCharsets.UTF_8));
            return true;
        } catch (Exception e) {
            failed.incrementAndGet();
            errors.add(entry.key() + "\t" + e.getClass().getSimpleName() + ": " + e.getMessage());
            return false;
        }
    }

    private void report(double seconds) throws IOException {
        if (!errors.isEmpty()) Io.atomicWrite(runs.resolve(run + ".errors.txt"), String.join("\n", errors));
        List<Integer> missing = List.of();
        if (options.part().seesEveryCid()) {
            missing = wanted.unseen();
            warn(missing, ".missing.txt", "are not in the SDF files");
            warn(wanted.seenMoreThanOnce(), ".repeated.txt",
                    "are in more than one SDF file and were rendered once per file under the same key");
        }
        System.out.printf("samples=%d failed=%d skipped_shards=%d missing_cids=%d skia_png_fallbacks=%d "
                        + "wall=%.1fs (%.1f img/s)%n", samples.get(), failed.get(), skippedShards.get(), missing.size(),
                Sample.SKIA_FALLBACKS.get(), seconds, samples.get() / seconds);
    }

    private void warn(List<Integer> cids, String suffix, String problem) throws IOException {
        if (cids.isEmpty()) return;
        Path list = runs.resolve(run + suffix);
        Io.atomicWrite(list, Io.lines(cids));
        System.out.printf("WARNING: %d CIDs of the list %s, see %s%n", cids.size(), problem, list);
    }
}
