package noauthbot.harness;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.atomic.AtomicIntegerArray;

final class CidList {
    private static final String[] VARIANTS = {null, Sample.VARIANT_STAR, Sample.VARIANT_PLAIN};

    private final int[] cids;
    private final int[] firstEntry;
    private final byte[] variants;
    private final AtomicIntegerArray timesSeen;

    private CidList(int[] cids, int[] firstEntry, byte[] variants) {
        this.cids = cids;
        this.firstEntry = firstEntry;
        this.variants = variants;
        this.timesSeen = new AtomicIntegerArray(cids.length);
    }

    static CidList read(Path path) throws IOException {
        long[] entries = sortedEntries(path);
        int[] cids = new int[entries.length];
        int[] firstEntry = new int[entries.length + 1];
        byte[] variants = new byte[entries.length];
        int distinct = 0;
        for (int i = 0; i < entries.length; i++) {
            int cid = cidOf(entries[i]);
            if (distinct == 0 || cids[distinct - 1] != cid) {
                cids[distinct] = cid;
                firstEntry[distinct] = i;
                distinct++;
            }
            variants[i] = (byte) variantOf(entries[i]);
        }
        firstEntry[distinct] = entries.length;
        return new CidList(Arrays.copyOf(cids, distinct), Arrays.copyOf(firstEntry, distinct + 1), variants);
    }

    private static long[] sortedEntries(Path path) throws IOException {
        long[] entries = new long[1 << 16];
        int count = 0;
        try (BufferedReader reader = Files.newBufferedReader(path)) {
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                String[] fields = line.split("\\s+");
                int variant = fields.length > 1 ? variantCode(fields[1], path, line) : 0;
                if (count == entries.length) entries = Arrays.copyOf(entries, count * 2);
                entries[count] = pack(Integer.parseInt(fields[0]), count, variant);
                count++;
            }
        }
        Arrays.sort(entries, 0, count);
        return Arrays.copyOf(entries, count);
    }

    private static long pack(int cid, int order, int variant) {
        return (long) cid << 32 | (long) order << 2 | variant;
    }

    private static int cidOf(long entry) {
        return (int) (entry >>> 32);
    }

    private static int variantOf(long entry) {
        return (int) (entry & 3);
    }

    private static int variantCode(String variant, Path path, String line) {
        for (int code = 1; code < VARIANTS.length; code++) {
            if (VARIANTS[code].equals(variant)) return code;
        }
        throw new IllegalArgumentException("bad variant in " + path + ": " + line);
    }

    int indexOf(int cid) {
        int index = Arrays.binarySearch(cids, cid);
        return index >= 0 ? index : -1;
    }

    boolean contains(int cid) {
        return indexOf(cid) >= 0;
    }

    int entries(int index) {
        return firstEntry[index + 1] - firstEntry[index];
    }

    String variant(int index, int occurrence) {
        return VARIANTS[variants[firstEntry[index] + occurrence]];
    }

    long totalEntries() {
        return variants.length;
    }

    void markSeen(int index) {
        timesSeen.incrementAndGet(index);
    }

    List<Integer> unseen() {
        return cidsSeen(0, 0);
    }

    List<Integer> seenMoreThanOnce() {
        return cidsSeen(2, Integer.MAX_VALUE);
    }

    private List<Integer> cidsSeen(int atLeast, int atMost) {
        List<Integer> result = new ArrayList<>();
        for (int i = 0; i < cids.length; i++) {
            int times = timesSeen.get(i);
            if (times >= atLeast && times <= atMost) result.add(cids[i]);
        }
        return result;
    }
}
