package noauthbot.harness;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.util.Collection;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;

final class Io {

    static String sdfStem(Path sdf) {
        String name = sdf.getFileName().toString();
        for (String extension : new String[]{".sdf.gz", ".sdf"}) {
            if (name.endsWith(extension)) return name.substring(0, name.length() - extension.length());
        }
        return name;
    }

    static void atomicWrite(Path destination, byte[] data) throws IOException {
        Path partial = destination.resolveSibling(destination.getFileName() + ".tmp");
        Files.write(partial, data);
        Files.move(partial, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }

    static void atomicWrite(Path destination, String text) throws IOException {
        atomicWrite(destination, text.getBytes(StandardCharsets.UTF_8));
    }

    static String lines(Collection<?> items) {
        StringBuilder text = new StringBuilder();
        for (Object item : items) text.append(item).append('\n');
        return text.toString();
    }

    static String timestamp() {
        return Instant.now().toString().replace(':', '-');
    }

    static ExecutorService threadPool(int threads, String name) {
        AtomicLong counter = new AtomicLong();
        return Executors.newFixedThreadPool(threads, task -> {
            Thread thread = new Thread(task, name + "-" + counter.incrementAndGet());
            thread.setDaemon(true);
            return thread;
        });
    }

    private Io() {
    }
}
