package cc.ioctl.telebot.util;

import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;

public final class IoUtils {
    private IoUtils() {
    }

    public static byte[] readFully(InputStream is) throws IOException {
        try (is) {
            return is.readAllBytes();
        }
    }

    public static void readExact(InputStream is, byte[] buffer, int offset, int length) throws IOException {
        if (is.readNBytes(buffer, offset, length) != length) throw new EOFException();
    }
}
