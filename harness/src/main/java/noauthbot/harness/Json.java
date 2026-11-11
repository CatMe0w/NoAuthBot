package noauthbot.harness;

public final class Json {
    private final StringBuilder out = new StringBuilder(4096);
    private boolean needComma = false;

    public Json beginObject() {
        separate();
        out.append('{');
        needComma = false;
        return this;
    }

    public Json endObject() {
        out.append('}');
        needComma = true;
        return this;
    }

    public Json beginArray() {
        separate();
        out.append('[');
        needComma = false;
        return this;
    }

    public Json endArray() {
        out.append(']');
        needComma = true;
        return this;
    }

    public Json key(String name) {
        separate();
        appendString(name);
        out.append(':');
        needComma = false;
        return this;
    }

    public Json value(String value) {
        separate();
        if (value == null) {
            out.append("null");
        } else {
            appendString(value);
        }
        needComma = true;
        return this;
    }

    public Json value(long value) {
        separate();
        out.append(value);
        needComma = true;
        return this;
    }

    public Json value(boolean value) {
        separate();
        out.append(value);
        needComma = true;
        return this;
    }

    public Json value(float value) {
        separate();
        out.append(Float.isFinite(value) ? Float.toString(value) : "null");
        needComma = true;
        return this;
    }

    public Json value(double value) {
        separate();
        out.append(Double.isFinite(value) ? Double.toString(value) : "null");
        needComma = true;
        return this;
    }

    private void separate() {
        if (needComma) out.append(',');
    }

    private void appendString(String s) {
        out.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
                }
            }
        }
        out.append('"');
    }

    @Override
    public String toString() {
        return out.toString();
    }
}
