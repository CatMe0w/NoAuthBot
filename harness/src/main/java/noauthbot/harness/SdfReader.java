package noauthbot.harness;

import java.io.BufferedReader;
import java.io.Closeable;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.function.IntPredicate;
import java.util.zip.GZIPInputStream;

public final class SdfReader implements Closeable {

    public static final String[] TAGS = {
            "PUBCHEM_COMPOUND_CID",
            "PUBCHEM_IUPAC_INCHIKEY",
            "PUBCHEM_ATOM_DEF_STEREO_COUNT",
            "PUBCHEM_ATOM_UDEF_STEREO_COUNT",
            "PUBCHEM_BOND_DEF_STEREO_COUNT",
            "PUBCHEM_BOND_UDEF_STEREO_COUNT",
            "PUBCHEM_COMPONENT_COUNT",
            "PUBCHEM_ISOTOPIC_ATOM_COUNT",
            "PUBCHEM_HEAVY_ATOM_COUNT",
    };
    private static final Set<String> TAG_SET = Set.of(TAGS);
    private static final String RECORD_END = "$$$$";
    private static final int BUFFER = 1 << 20;

    public static final class Record {
        public final String molblock;
        public final Map<String, String> tags;
        public final int cid;

        Record(String molblock, Map<String, String> tags) {
            this.molblock = molblock;
            this.tags = tags;
            String cidTag = tags.get("PUBCHEM_COMPOUND_CID");
            this.cid = cidTag == null ? -1 : Integer.parseInt(cidTag.trim());
        }

        public String tag(String name) {
            return tags.getOrDefault(name, "");
        }
    }

    private final BufferedReader reader;

    public SdfReader(Path path) throws IOException {
        InputStream in = new FileInputStream(path.toFile());
        if (path.getFileName().toString().endsWith(".gz")) in = new GZIPInputStream(in, BUFFER);
        reader = new BufferedReader(new InputStreamReader(in, StandardCharsets.ISO_8859_1), BUFFER);
    }

    public Record next() throws IOException {
        return readRecord(null);
    }

    public Record next(IntPredicate wanted) throws IOException {
        while (true) {
            String title = reader.readLine();
            if (title == null) return null;
            int cid;
            try {
                cid = Integer.parseInt(title.trim());
            } catch (NumberFormatException e) {
                throw new IOException("record title is not a CID: '" + title + "'");
            }
            if (wanted.test(cid)) {
                Record record = readRecord(title);
                if (record == null || record.cid != cid) throw new IOException("CID tag mismatch for title " + cid);
                return record;
            }
            skipRecord();
        }
    }

    private void skipRecord() throws IOException {
        String line;
        do {
            line = reader.readLine();
        } while (line != null && !line.equals(RECORD_END));
    }

    private Record readRecord(String title) throws IOException {
        StringBuilder molblock = new StringBuilder(8192);
        Map<String, String> tags = new HashMap<>();
        boolean inMolblock = true;
        boolean sawAnything = title != null;
        String pendingTag = null;
        if (title != null) molblock.append(title).append('\n');

        String line;
        while ((line = reader.readLine()) != null) {
            sawAnything = true;
            if (line.equals(RECORD_END)) return new Record(molblock.toString(), tags);
            if (inMolblock) {
                molblock.append(line).append('\n');
                if (line.startsWith("M  END")) inMolblock = false;
            } else if (pendingTag != null) {
                tags.put(pendingTag, line.trim());
                pendingTag = null;
            } else if (line.startsWith("> <")) {
                int end = line.indexOf('>', 3);
                String name = end > 0 ? line.substring(3, end) : "";
                if (TAG_SET.contains(name)) pendingTag = name;
            }
        }
        return sawAnything && molblock.length() > 0 ? new Record(molblock.toString(), tags) : null;
    }

    @Override
    public void close() throws IOException {
        reader.close();
    }
}
