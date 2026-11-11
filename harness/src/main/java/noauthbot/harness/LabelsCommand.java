package noauthbot.harness;

import java.io.Closeable;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.zip.GZIPOutputStream;

final class LabelsCommand {
    private static final int BATCH_SIZE = 64;
    private static final int BATCHES_PER_THREAD = 4;

    private sealed interface Outcome permits Label, Intractable, Failure {
    }

    private record Label(String json) implements Outcome {
    }

    private record Intractable(String line) implements Outcome {
    }

    private record Failure() implements Outcome {
    }

    private static final class Tally {
        long candidates;
        long errors;
        final List<String> intractable = new ArrayList<>();
    }

    private final List<Path> sdfs;
    private final Path out;
    private final int threads;
    private final Map<String, String> versionInfo;

    LabelsCommand(Args args) throws Exception {
        sdfs = args.paths("--sdf");
        out = Paths.get(args.required("--out"));
        threads = args.getInt("--threads", Runtime.getRuntime().availableProcessors());
        versionInfo = Provenance.versionInfo();
    }

    void run() throws Exception {
        Files.createDirectories(out);
        Sample.prewarm();
        ExecutorService workers = Io.threadPool(threads, "labels");
        for (Path sdf : sdfs) labelFile(sdf, workers);
        workers.shutdown();
    }

    private void labelFile(Path sdf, ExecutorService workers) throws Exception {
        String stem = Io.sdfStem(sdf);
        Path destination = out.resolve(stem + ".labels.jsonl.gz");
        if (Files.exists(destination)) {
            System.out.println("skip " + destination);
            return;
        }
        Path partial = out.resolve(stem + ".labels.jsonl.gz.tmp");
        long started = System.nanoTime();
        Tally tally = new Tally();
        long records;
        try (SdfReader reader = new SdfReader(sdf); GzipText labels = new GzipText(partial)) {
            records = OrderedBatches.run(workers, BATCH_SIZE, threads * BATCHES_PER_THREAD, reader::next,
                    this::labelBatch, outcomes -> collect(outcomes, labels, tally));
            labels.finish();
        }

        Files.move(partial, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        Io.atomicWrite(out.resolve(stem + ".intractable.tsv"), String.join("\n", tally.intractable));
        System.out.printf("ok %s records=%d candidates=%d errors=%d intractable=%d %.1fs%n", destination, records,
                tally.candidates, tally.errors, tally.intractable.size(), (System.nanoTime() - started) / 1e9);
    }

    private List<Outcome> labelBatch(List<SdfReader.Record> batch) {
        List<Outcome> outcomes = new ArrayList<>(batch.size());
        for (SdfReader.Record record : batch) {
            try {
                String label = Sample.labelOnly(record, versionInfo);
                if (label != null) outcomes.add(new Label(label));
            } catch (ChainBudget.IntractableException e) {
                outcomes.add(new Intractable(record.cid + "\t" + e.getMessage()));
            } catch (Exception e) {
                outcomes.add(new Failure());
            }
        }
        return outcomes;
    }

    private static void collect(List<Outcome> outcomes, GzipText labels, Tally tally) throws IOException {
        for (Outcome outcome : outcomes) {
            if (outcome instanceof Label label) {
                labels.writeLine(label.json());
                tally.candidates++;
            } else if (outcome instanceof Intractable intractable) {
                tally.intractable.add(intractable.line());
            } else {
                tally.errors++;
            }
        }
    }

    private static final class GzipText implements Closeable {
        private final FileOutputStream file;
        private final GZIPOutputStream gzip;
        private final Writer writer;

        GzipText(Path path) throws IOException {
            file = new FileOutputStream(path.toFile());
            gzip = new GZIPOutputStream(file, 1 << 20);
            writer = new OutputStreamWriter(gzip, StandardCharsets.UTF_8);
        }

        void writeLine(String line) throws IOException {
            writer.write(line);
            writer.write('\n');
        }

        void finish() throws IOException {
            writer.flush();
            gzip.finish();
            file.getFD().sync();
        }

        @Override
        public void close() throws IOException {
            writer.close();
        }
    }
}
