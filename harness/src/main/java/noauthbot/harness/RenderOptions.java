package noauthbot.harness;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

record RenderOptions(List<Path> sdfs, Path cids, Path out, int threads, int readers, int shardSize, long seed,
                     double starRatio, String prefix, int pngLevel, String pngFilterName, int zstdLevel, Part part) {

    record Part(int index, int count, boolean byFile) {

        static Part parse(String spec, String by) {
            String[] fields = spec.split("/");
            return new Part(Integer.parseInt(fields[0]), Integer.parseInt(fields[1]), by.equals("file"));
        }

        boolean ownsFile(int fileIndex) {
            return !byFile || fileIndex % count == index;
        }

        boolean ownsChunk(int chunkIndex) {
            return byFile || chunkIndex % count == index;
        }

        boolean seesEveryCid() {
            return index == 0 && (!byFile || count == 1);
        }

        @Override
        public String toString() {
            return index + "/" + count + (byFile ? " by file" : " by chunk");
        }
    }

    static RenderOptions parse(Args args) {
        List<Path> sdfs = new ArrayList<>(args.paths("--sdf"));
        Collections.sort(sdfs);
        RenderOptions options = new RenderOptions(
                List.copyOf(sdfs),
                Paths.get(args.required("--cids")),
                Paths.get(args.required("--out")),
                args.getInt("--threads", Runtime.getRuntime().availableProcessors()),
                args.getInt("--readers", Math.min(sdfs.size(), 4)),
                args.getInt("--shard-size", 4096),
                Long.parseLong(args.get("--seed", "0")),
                Double.parseDouble(args.get("--star-ratio", "0.5")),
                args.get("--prefix", "shard"),
                args.getInt("--png-level", 0),
                args.get("--png-filter", "none"),
                args.getInt("--zstd", 3),
                Part.parse(args.get("--part", "0/1"), args.get("--part-by", "chunk")));
        options.pngFilter();
        return options;
    }

    int pngFilter() {
        return switch (pngFilterName) {
            case "none" -> FastPng.FILTER_NONE;
            case "up" -> FastPng.FILTER_UP;
            default -> throw new IllegalArgumentException("--png-filter none|up");
        };
    }

    String shardExtension() {
        return zstdLevel > 0 ? ".tar.zst" : ".tar";
    }
}
