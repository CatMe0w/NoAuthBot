package noauthbot.harness;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.function.Function;

final class OrderedBatches {

    interface Source<T> {
        T next() throws Exception;
    }

    interface Sink<R> {
        void accept(R result) throws Exception;
    }

    static <T, R> long run(ExecutorService workers, int batchSize, int window, Source<T> source,
                           Function<List<T>, R> work, Sink<R> sink) throws Exception {
        ArrayDeque<Future<R>> pending = new ArrayDeque<>();
        long items = 0;
        boolean exhausted = false;
        while (true) {
            while (!exhausted && pending.size() < window) {
                List<T> batch = readBatch(source, batchSize);
                exhausted = batch.size() < batchSize;
                if (batch.isEmpty()) break;
                items += batch.size();
                pending.add(workers.submit(() -> work.apply(batch)));
            }
            if (pending.isEmpty()) return items;
            sink.accept(pending.poll().get());
        }
    }

    private static <T> List<T> readBatch(Source<T> source, int batchSize) throws Exception {
        List<T> batch = new ArrayList<>(batchSize);
        T item;
        while (batch.size() < batchSize && (item = source.next()) != null) batch.add(item);
        return batch;
    }

    private OrderedBatches() {
    }
}
