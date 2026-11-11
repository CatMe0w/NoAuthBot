package noauthbot.harness;

final class Seeds {

    static long splitmix64(long z) {
        z += 0x9E3779B97F4A7C15L;
        z = (z ^ (z >>> 30)) * 0xBF58476D1CE4E5B9L;
        z = (z ^ (z >>> 27)) * 0x94D049BB133111EBL;
        return z ^ (z >>> 31);
    }

    static long forSample(long globalSeed, int cid, int occurrence) {
        return splitmix64(globalSeed ^ splitmix64(((long) cid << 16) ^ occurrence));
    }

    static double unitInterval(long seed) {
        return (splitmix64(seed) >>> 11) * 0x1.0p-53;
    }

    private Seeds() {
    }
}
