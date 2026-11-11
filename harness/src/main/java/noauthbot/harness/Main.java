package noauthbot.harness;

public final class Main {

    public static void main(String[] args) throws Exception {
        if (args.length == 0) usage();
        Args options = new Args(args, 1);
        switch (args[0]) {
            case "render" -> new RenderCommand(options).run();
            case "labels" -> new LabelsCommand(options).run();
            default -> usage();
        }
    }

    private static void usage() {
        System.err.println(String.join("\n",
                "usage: run.sh <command> [options]",
                "  labels --sdf F... --out DIR [--threads N]",
                "         per SDF file: candidate labels (+molblock) as .labels.jsonl.gz, and rejected molecules as .intractable.tsv",
                "  render --sdf F... --cids FILE --out DIR [--threads N] [--readers N] [--shard-size 4096]",
                "         [--seed 0] [--star-ratio 0.5] [--prefix NAME] [--png-level 0] [--png-filter none|up] [--zstd 3]",
                "         [--part i/P] [--part-by chunk|file]",
                "see README for input and output formats"));
        System.exit(1);
    }
}
