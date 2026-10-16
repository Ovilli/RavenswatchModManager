// Bring a freshly imported build up to what we know about the game.
//
// A new game build lands in Ghidra as ~60k FUN_ blobs: auto-analysis misses
// thousands of .pdata functions, and none of our symbol names, notes or the
// renames made in the previous build's program carry over. This applies, in
// order:
//   1. a function at every .pdata RUNTIME_FUNCTION start that is not inside one
//      (BinExport, the decompiler and the MCP only see defined functions);
//   2. names + plate comments from <knowledge.json>, which
//      tools/ghidra_apply_knowledge.py builds from data/symbols.json and from
//      BinDiff matches against the previous build's renames.
// A USER_DEFINED name already on a function is kept unless the entry says
// "force" (symbols.json entries do: the map is the source of truth).
//
// Args: <knowledge.json> [dry]       Saves when run without -readOnly.
// @category RSMM
import com.google.gson.*;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.nio.charset.StandardCharsets;

public class ApplyRsmmKnowledge extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        boolean dry = args.length > 1 && args[1].equals("dry");
        JsonObject k;
        try (Reader r = new InputStreamReader(new FileInputStream(args[0]), StandardCharsets.UTF_8)) {
            k = JsonParser.parseReader(r).getAsJsonObject();
        }
        FunctionManager fm = currentProgram.getFunctionManager();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Address base = currentProgram.getImageBase();

        // 1. .pdata starts. Each entry: u32 begin RVA, u32 end RVA, u32 unwind.
        int pdata = 0, pdataFail = 0;
        MemoryBlock pb = currentProgram.getMemory().getBlock(".pdata");
        if (pb != null) {
            Memory mem = currentProgram.getMemory();
            for (long o = 0; o + 12 <= pb.getSize(); o += 12) {
                if (monitor.isCancelled()) return;
                int rva = mem.getInt(pb.getStart().add(o));
                if (rva == 0) continue;
                Address a = base.add(rva & 0xffffffffL);
                if (fm.getFunctionContaining(a) != null) continue; // chained part, or known
                pdata++;
                if (dry) continue;
                if (getInstructionAt(a) == null) disassemble(a);
                if (!new CreateFunctionCmd(a).applyTo(currentProgram, monitor)) pdataFail++;
            }
        }
        println("RSMM pdata: " + pdata + " missing function start(s) "
                + (dry ? "found" : "defined, " + pdataFail + " failed"));

        // 2. Names and comments.
        int named = 0, kept = 0, created = 0, missing = 0, labels = 0;
        for (JsonElement e : k.getAsJsonArray("entries")) {
            JsonObject o = e.getAsJsonObject();
            Address a = sp.getAddress(o.get("addr").getAsString());
            String name = o.get("name").getAsString();
            boolean force = o.has("force") && o.get("force").getAsBoolean();
            String note = o.has("note") ? o.get("note").getAsString() : null;
            if (o.has("kind") && o.get("kind").getAsString().equals("data")) {
                if (!dry) createLabel(a, name, true, SourceType.USER_DEFINED);
                if (!dry && note != null) setPlateComment(a, note);
                labels++;
                continue;
            }
            Function f = fm.getFunctionAt(a);
            if (f == null) {
                if (fm.getFunctionContaining(a) != null) { missing++; continue; } // mid-function
                if (dry) { created++; named++; continue; }
                if (getInstructionAt(a) == null) disassemble(a);
                new CreateFunctionCmd(a).applyTo(currentProgram, monitor);
                f = fm.getFunctionAt(a);
                if (f == null) { missing++; continue; }
                created++;
            }
            if (!force && f.getSymbol().getSource() == SourceType.USER_DEFINED) { kept++; continue; }
            if (!dry) {
                f.setName(name, SourceType.USER_DEFINED);
                if (note != null) f.setComment(note);
            }
            named++;
        }
        println("RSMM names: " + named + " named (" + created + " newly defined), " + kept
                + " kept an existing user name, " + missing + " not a function start, "
                + labels + " data label(s)");
    }
}
