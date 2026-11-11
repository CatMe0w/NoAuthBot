package noauthbot.harness;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

final class Provenance {
    static final String HARNESS_VERSION = "2.0.0";
    static final String RENDERER = "skija-linux 0.93.1";

    static Map<String, String> versionInfo() throws IOException {
        Map<String, String> info = new LinkedHashMap<>();
        info.put("harness", HARNESS_VERSION);
        info.put("renderer", RENDERER);
        try (InputStream in = Provenance.class.getClassLoader().getResourceAsStream("generator-commit.txt")) {
            if (in == null) throw new IOException("generator-commit.txt missing from the jar");
            info.put("generator_commit", new String(in.readAllBytes(), StandardCharsets.US_ASCII).trim());
        }
        return info;
    }

    static void write(Json json, Map<String, String> info) {
        json.key("generator").beginObject();
        for (Map.Entry<String, String> entry : info.entrySet()) json.key(entry.getKey()).value(entry.getValue());
        json.endObject();
    }

    private Provenance() {
    }
}
