package noauthbot.harness;

import org.jetbrains.skija.Data;
import org.jetbrains.skija.FontMgr;
import org.jetbrains.skija.Typeface;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;

final class Fonts {

    // MoleculeRender's Typeface is private, so the harness loads the same TTF for its own text measurements
    static Typeface roboto() {
        return Holder.ROBOTO;
    }

    private static final class Holder {
        static final Typeface ROBOTO = load("Roboto-Regular.ttf");
    }

    private static Typeface load(String resource) {
        try (InputStream in = Fonts.class.getClassLoader().getResourceAsStream(resource)) {
            if (in == null) throw new IllegalStateException(resource + " missing");
            return FontMgr.getDefault().makeFromData(Data.makeFromBytes(in.readAllBytes()));
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    private Fonts() {
    }
}
