package noauthbot.harness;

import cc.ioctl.neoauth3bot.chiral.MdlMolParser;
import cc.ioctl.neoauth3bot.chiral.Molecule;
import cc.ioctl.neoauth3bot.chiral.MoleculeRender;
import org.jetbrains.skija.Data;
import org.jetbrains.skija.Image;

import java.util.ArrayList;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

public final class Sample {

    public static final String VARIANT_STAR = "star";
    public static final String VARIANT_PLAIN = "plain";
    public static final AtomicLong SKIA_FALLBACKS = new AtomicLong();

    public final byte[] png;
    public final String json;

    private Sample(byte[] png, String json) {
        this.png = png;
        this.json = json;
    }

    // MoleculeRender initialises a static Typeface lazily without locking
    static void prewarm() throws Exception {
        String molblock = "\n\n\n  3  2  0  0  0  0  0  0  0  0999 V2000\n"
                + "    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n"
                + "    1.0000    0.5000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0\n"
                + "    2.0000    0.0000    0.0000 N   0  0  0  0  0  0  0  0  0  0  0  0\n"
                + "  1  2  1  0  0  0  0\n  2  3  1  0  0  0  0\nM  END\n";
        Molecule molecule = MdlMolParser.parseString(molblock);
        try (Image image = MoleculeRender.renderMoleculeAsImage(molecule,
                MoleculeRender.calculateRenderRect(molecule, Layout.CANVAS_SIZE))) {
            image.encodeToData().close();
        }
    }

    public static Sample render(SdfReader.Record record, String variant, long seed, String key,
                                Map<String, String> versionInfo, int pngLevel, int pngFilter) throws Exception {
        Molecule molecule = MdlMolParser.parseString(record.molblock);
        ChainBudget.check(molecule);
        Layout layout = Layout.of(molecule);
        layout.config().shownChiralCarbons = VARIANT_STAR.equals(variant)
                ? new ArrayList<>(layout.chirals()) : new ArrayList<>();
        byte[] png;
        try (Image image = MoleculeRender.renderMoleculeAsImage(molecule, layout.config())) {
            png = encode(image, pngLevel, pngFilter);
        }
        String json = LabelJson.open(record, variant, seed, key, versionInfo, molecule, layout).endObject().toString();
        return new Sample(png, json);
    }

    // production calls img.encodeToData(); same pixels, as grayscale PNG
    private static byte[] encode(Image image, int pngLevel, int pngFilter) {
        byte[] png = FastPng.encode(image, pngLevel, pngFilter);
        if (png != null) return png;
        SKIA_FALLBACKS.incrementAndGet();
        try (Data data = image.encodeToData()) {
            if (data == null) throw new IllegalStateException("failed to encode image");
            return data.getBytes();
        }
    }

    public static String labelOnly(SdfReader.Record record, Map<String, String> versionInfo) throws Exception {
        Molecule molecule = MdlMolParser.parseString(record.molblock);
        ChainBudget.check(molecule);
        if (!isCandidate(molecule)) return null;
        Layout layout = Layout.of(molecule);
        return LabelJson.open(record, VARIANT_STAR, 0, Integer.toString(record.cid), versionInfo, molecule, layout)
                .key("rule_pass").value(passesRule(layout.chirals().size(), molecule.atomCount()))
                .key("molblock").value(record.molblock)
                .endObject().toString();
    }

    private static boolean isCandidate(Molecule molecule) {
        if (molecule.rangeX() == 0 || molecule.rangeY() == 0) return false;
        int possiblyChiral = 0;
        for (int atom = 1; atom <= molecule.atomCount(); atom++) {
            if (ChiralAmbiguity.chiralFraction(molecule, atom) > 0) possiblyChiral++;
        }
        return passesRule(possiblyChiral, molecule.atomCount());
    }

    // the generator's candidate rule (MoleculeFilter.kt)
    static boolean passesRule(int chiralCount, int atomCount) {
        return chiralCount > 3 || chiralCount * atomCount > 200;
    }
}
