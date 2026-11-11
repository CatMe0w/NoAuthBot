package noauthbot.harness;

import org.jetbrains.skija.Image;
import org.jetbrains.skija.Pixmap;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.zip.CRC32;
import java.util.zip.Deflater;

public final class FastPng {

    public static final int FILTER_NONE = 0;
    public static final int FILTER_UP = 2;

    private static final byte[] SIGNATURE = {(byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    private static final int RGBA = 4;
    private static final byte OPAQUE = (byte) 0xff;

    private static final class Scratch {
        byte[] rgbaRow = new byte[0];
        byte[] previousRow = new byte[0];
        byte[] currentRow = new byte[0];
        byte[] filtered = new byte[0];
        final byte[] deflated = new byte[1 << 16];
        final Deflater deflater = new Deflater();

        void ensure(int width, int height) {
            if (rgbaRow.length < width * RGBA) {
                rgbaRow = new byte[width * RGBA];
                previousRow = new byte[width];
                currentRow = new byte[width];
            }
            int filteredLength = (width + 1) * height;
            if (filtered.length < filteredLength) filtered = new byte[filteredLength];
        }
    }

    private static final ThreadLocal<Scratch> SCRATCH = ThreadLocal.withInitial(Scratch::new);

    public static byte[] encode(Image image, int level, int filter) {
        try (Pixmap pixmap = new Pixmap()) {
            if (!image.peekPixels(pixmap)) return null;
            if (pixmap.getInfo().getColorInfo().getColorType().getBytesPerPixel() != RGBA) return null;
            int width = image.getWidth(), height = image.getHeight();
            Scratch scratch = SCRATCH.get();
            scratch.ensure(width, height);
            if (!filterRows(pixmap, width, height, filter, scratch)) return null;
            return container(width, height, deflate(scratch, (width + 1) * height, level));
        }
    }

    private static boolean filterRows(Pixmap pixmap, int width, int height, int filter, Scratch scratch) {
        int rowBytes = pixmap.getRowBytes();
        ByteBuffer pixels = pixmap.getBuffer();
        byte[] rgba = scratch.rgbaRow, filtered = scratch.filtered;
        byte[] previous = scratch.previousRow, current = scratch.currentRow;
        for (int y = 0; y < height; y++) {
            pixels.get(y * rowBytes, rgba, 0, width * RGBA);
            for (int x = 0, p = 0; x < width; x++, p += RGBA) {
                byte gray = rgba[p];
                if (rgba[p + 3] != OPAQUE || gray != rgba[p + 1] || gray != rgba[p + 2]) return false;
                current[x] = gray;
            }
            int offset = y * (width + 1);
            filtered[offset] = (byte) filter;
            if (filter == FILTER_NONE || y == 0) {
                System.arraycopy(current, 0, filtered, offset + 1, width);
            } else {
                for (int x = 0; x < width; x++) filtered[offset + 1 + x] = (byte) (current[x] - previous[x]);
            }
            byte[] swap = previous;
            previous = current;
            current = swap;
        }
        return true;
    }

    private static byte[] deflate(Scratch scratch, int length, int level) {
        Deflater deflater = scratch.deflater;
        deflater.reset();
        deflater.setLevel(level);
        deflater.setInput(scratch.filtered, 0, length);
        deflater.finish();
        ByteArrayOutputStream out = new ByteArrayOutputStream(level == 0 ? length + 1024 : length / 16);
        while (!deflater.finished()) out.write(scratch.deflated, 0, deflater.deflate(scratch.deflated));
        return out.toByteArray();
    }

    private static byte[] container(int width, int height, byte[] idat) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(idat.length + 64);
        out.writeBytes(SIGNATURE);
        byte[] header = new byte[13];
        putInt(header, 0, width);
        putInt(header, 4, height);
        header[8] = 8;
        chunk(out, "IHDR", header);
        chunk(out, "IDAT", idat);
        chunk(out, "IEND", new byte[0]);
        return out.toByteArray();
    }

    private static void chunk(ByteArrayOutputStream out, String type, byte[] data) {
        byte[] length = new byte[4];
        putInt(length, 0, data.length);
        out.writeBytes(length);
        byte[] typeBytes = type.getBytes(StandardCharsets.US_ASCII);
        out.writeBytes(typeBytes);
        out.writeBytes(data);
        CRC32 crc = new CRC32();
        crc.update(typeBytes);
        crc.update(data);
        byte[] checksum = new byte[4];
        putInt(checksum, 0, (int) crc.getValue());
        out.writeBytes(checksum);
    }

    private static void putInt(byte[] target, int offset, int value) {
        target[offset] = (byte) (value >>> 24);
        target[offset + 1] = (byte) (value >>> 16);
        target[offset + 2] = (byte) (value >>> 8);
        target[offset + 3] = (byte) value;
    }
}
