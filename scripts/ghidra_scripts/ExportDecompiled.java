// Export every function's decompiled C to JSON-Lines.
//
// Usage (invoked by scripts/ghidra_export.py):
//     analyzeHeadless ... -postScript ExportDecompiled.java <out.jsonl>
//
// Each line: {"addr":"0x...","name":"...","sig":"...","size":N,"code":"..."}
// `code` is the full decompiled C source for the function. Skips thunks
// + functions whose body is empty (Ghidra sentinel).
//
//@category RSMM
//@runtime Java

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.util.Iterator;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.util.task.ConsoleTaskMonitor;

public class ExportDecompiled extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("ExportDecompiled requires output path");
            return;
        }
        String outPath = args[0];

        DecompInterface decomp = new DecompInterface();
        DecompileOptions opts = new DecompileOptions();
        decomp.setOptions(opts);
        decomp.toggleCCode(true);
        decomp.toggleSyntaxTree(false);
        decomp.setSimplificationStyle("decompile");
        if (!decomp.openProgram(currentProgram)) {
            printerr("Failed to open program in DecompInterface");
            return;
        }

        FunctionIterator it = currentProgram.getListing().getFunctions(true);
        int total = 0;
        int written = 0;
        int skippedThunk = 0;
        int skippedEmpty = 0;
        int errs = 0;
        ConsoleTaskMonitor monitor = new ConsoleTaskMonitor();

        try (BufferedWriter w = new BufferedWriter(new FileWriter(outPath))) {
            while (it.hasNext() && !monitor.isCancelled()) {
                Function f = it.next();
                total++;
                if (f.isThunk()) { skippedThunk++; continue; }
                try {
                    DecompileResults res = decomp.decompileFunction(f, 60, monitor);
                    if (res == null || !res.decompileCompleted()) { errs++; continue; }
                    String code = res.getDecompiledFunction() != null
                            ? res.getDecompiledFunction().getC()
                            : null;
                    if (code == null || code.isBlank()) { skippedEmpty++; continue; }
                    Address entry = f.getEntryPoint();
                    String name = f.getName();
                    String sig = f.getSignature(false).getPrototypeString(false);
                    long size = f.getBody().getNumAddresses();
                    StringBuilder line = new StringBuilder(64 + code.length());
                    line.append("{\"addr\":\"0x").append(Long.toHexString(entry.getOffset()))
                        .append("\",\"name\":").append(jsonEscape(name))
                        .append(",\"sig\":").append(jsonEscape(sig))
                        .append(",\"size\":").append(size)
                        .append(",\"code\":").append(jsonEscape(code))
                        .append("}\n");
                    w.write(line.toString());
                    written++;
                    if (written % 200 == 0) {
                        println("decompiled " + written + " / " + total + " functions...");
                        w.flush();
                    }
                } catch (Exception e) {
                    errs++;
                }
            }
        }

        decomp.dispose();
        println("done. total=" + total + " written=" + written
                + " skipped_thunk=" + skippedThunk + " skipped_empty=" + skippedEmpty
                + " errs=" + errs);
    }

    private static String jsonEscape(String s) {
        if (s == null) return "null";
        StringBuilder b = new StringBuilder(s.length() + 16);
        b.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\\': b.append("\\\\"); break;
                case '"':  b.append("\\\""); break;
                case '\b': b.append("\\b"); break;
                case '\f': b.append("\\f"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
            }
        }
        b.append('"');
        return b.toString();
    }
}
