// Export the current program to BinDiff's .BinExport format, headless.
//
// The GUI has an Export dialog for this; headless does not, and a game patch is
// exactly when the project must stay closed (analyzeHeadless refuses a LOCKED
// project, and the GUI/MCP bridge holds the lock — see CLAUDE.md).
//
//   analyzeHeadless <projdir> <proj> -process <program> -noanalysis \
//     -scriptPath tools/ghidra_scripts -postScript BinExportHeadless.java <out.BinExport>
//
// Requires the BinExport extension (ships inside the BinDiff .deb at
// extra/ghidra/BinExport; install into <ghidra user dir>/Extensions/).
//
//@category BinDiff
import java.io.File;

import ghidra.app.script.GhidraScript;
import ghidra.app.util.exporter.Exporter;
import ghidra.util.classfinder.ClassSearcher;

public class BinExportHeadless extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("usage: BinExportHeadless.java <out.BinExport>");
            return;
        }

        // Located by NAME rather than by class, so the script keeps working
        // across BinExport releases that move the class around.
        Exporter binexport = null;
        for (Exporter e : ClassSearcher.getInstances(Exporter.class)) {
            if (e.getName().toLowerCase().contains("binexport")) {
                binexport = e;
                break;
            }
        }
        if (binexport == null) {
            // Fail loudly. A silent skip here produces an empty diff later,
            // and an empty diff reads as "nothing moved" — the one wrong
            // answer this whole pipeline exists to prevent on patch day.
            printerr("BINEXPORT-MISSING: the BinExport extension is not installed "
                     + "for this Ghidra. Copy it from the BinDiff install "
                     + "(extra/ghidra/BinExport) into <ghidra user dir>/Extensions/ "
                     + "and add a matching ghidraVersion= line to its "
                     + "extension.properties.");
            throw new IllegalStateException("BinExport extension not found");
        }

        File out = new File(args[0]);
        if (!binexport.export(out, currentProgram, null, monitor)) {
            throw new IllegalStateException("BinExport reported failure for " + out);
        }
        println("BinExport wrote " + out + " (" + out.length() + " bytes)");
    }
}
