package noauthbot.harness;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

final class Args {
    private final Map<String, List<String>> values = new HashMap<>();

    Args(String[] args, int start) {
        String option = null;
        for (int i = start; i < args.length; i++) {
            if (args[i].startsWith("--")) {
                option = args[i];
                values.computeIfAbsent(option, k -> new ArrayList<>());
            } else if (option != null) {
                values.get(option).add(args[i]);
            } else {
                throw new IllegalArgumentException("unexpected argument " + args[i]);
            }
        }
    }

    String get(String option, String fallback) {
        List<String> given = values.get(option);
        return given == null || given.isEmpty() ? fallback : given.get(0);
    }

    String required(String option) {
        String value = get(option, null);
        if (value == null) throw new IllegalArgumentException("missing " + option);
        return value;
    }

    int getInt(String option, int fallback) {
        return Integer.parseInt(get(option, Integer.toString(fallback)));
    }

    List<Path> paths(String option) {
        List<String> given = values.get(option);
        if (given == null || given.isEmpty()) throw new IllegalArgumentException("missing " + option);
        List<Path> paths = new ArrayList<>();
        for (String s : given) paths.add(Paths.get(s));
        return paths;
    }
}
