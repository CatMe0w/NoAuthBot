package noauthbot.harness;

import com.github.luben.zstd.ZstdOutputStream;

import java.io.BufferedOutputStream;
import java.io.Closeable;
import java.io.FileOutputStream;
import java.io.FilterOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;

public final class TarWriter implements Closeable {
    private static final int BLOCK = 512;
    private static final int MAX_NAME = 99;

    private final FileOutputStream file;
    private final OutputStream stream;

    public TarWriter(Path path, int zstdLevel) throws IOException {
        file = new FileOutputStream(path.toFile());
        OutputStream chain = new FilterOutputStream(file) {
            @Override
            public void write(byte[] bytes, int offset, int length) throws IOException {
                out.write(bytes, offset, length);
            }

            @Override
            public void close() throws IOException {
                flush();
            }
        };
        if (zstdLevel > 0) {
            ZstdOutputStream zstd = new ZstdOutputStream(chain, zstdLevel);
            zstd.setChecksum(true);
            chain = zstd;
        }
        stream = new BufferedOutputStream(chain, 1 << 20);
    }

    public void add(String name, byte[] data) throws IOException {
        stream.write(header(name, data.length));
        stream.write(data);
        stream.write(new byte[(BLOCK - data.length % BLOCK) % BLOCK]);
    }

    private static byte[] header(String name, int size) {
        byte[] nameBytes = name.getBytes(StandardCharsets.US_ASCII);
        if (nameBytes.length > MAX_NAME) throw new IllegalArgumentException("tar entry name too long: " + name);
        byte[] header = new byte[BLOCK];
        System.arraycopy(nameBytes, 0, header, 0, nameBytes.length);
        octal(header, 100, 8, 0644);
        octal(header, 108, 8, 0);
        octal(header, 116, 8, 0);
        octal(header, 124, 12, size);
        octal(header, 136, 12, 0);
        for (int i = 148; i < 156; i++) header[i] = ' ';
        header[156] = '0';
        byte[] magic = "ustar\0".getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(magic, 0, header, 257, magic.length);
        header[263] = '0';
        header[264] = '0';
        long checksum = 0;
        for (byte b : header) checksum += b & 0xff;
        octal(header, 148, 7, checksum);
        header[155] = ' ';
        return header;
    }

    private static void octal(byte[] header, int offset, int length, long value) {
        byte[] digits = Long.toOctalString(value).getBytes(StandardCharsets.US_ASCII);
        int width = length - 1;
        for (int i = 0; i < width; i++) header[offset + i] = '0';
        System.arraycopy(digits, 0, header, offset + width - digits.length, digits.length);
        header[offset + width] = 0;
    }

    @Override
    public void close() throws IOException {
        stream.write(new byte[2 * BLOCK]);
        stream.close();
        file.getFD().sync();
        file.close();
    }
}
