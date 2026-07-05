// Define functions at the given addresses (disassemble + createFunction if
// needed), then decompile each and write JSON-Lines to the output path.
//
// Usage:
//     analyzeHeadless <proj> <name> -process <prog> -noanalysis \
//         -postScript DefineAndDecompile.java <out.jsonl> 0x140319e40 0x...
//
// Each line: {"addr":"0x...","name":"...","code":"..."}
//
//@category RSMM
//@runtime Java

import java.io.BufferedWriter;
import java.io.FileWriter;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.util.task.ConsoleTaskMonitor;

public class DefineAndDecompile extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            printerr("usage: DefineAndDecompile <out.jsonl> <addr> [addr...]");
            return;
        }
        String outPath = args[0];

        DecompInterface decomp = new DecompInterface();
        decomp.setOptions(new DecompileOptions());
        decomp.toggleCCode(true);
        decomp.setSimplificationStyle("decompile");
        if (!decomp.openProgram(currentProgram)) {
            printerr("DecompInterface.openProgram failed");
            return;
        }

        BufferedWriter out = new BufferedWriter(new FileWriter(outPath));
        for (int i = 1; i < args.length; i++) {
            Address addr = toAddr(Long.decode(args[i]));
            Function fn = getFunctionAt(addr);
            if (fn == null) {
                DisassembleCommand dis = new DisassembleCommand(addr, null, true);
                dis.applyTo(currentProgram, monitor);
                CreateFunctionCmd mk = new CreateFunctionCmd(addr);
                mk.applyTo(currentProgram, monitor);
                fn = getFunctionAt(addr);
            }
            if (fn == null) {
                println("FAILED to define function at " + args[i]);
                continue;
            }
            DecompileResults res = decomp.decompileFunction(fn, 120, new ConsoleTaskMonitor());
            String code = (res != null && res.decompileCompleted())
                    ? res.getDecompiledFunction().getC() : "";
            out.write("{\"addr\":\"" + args[i] + "\",\"name\":\"" + fn.getName()
                    + "\",\"code\":" + jsonStr(code) + "}\n");
            println("decompiled " + args[i] + " -> " + fn.getName());
        }
        out.close();
        decomp.dispose();
    }

    private static String jsonStr(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
            }
        }
        return b.append('"').toString();
    }
}
