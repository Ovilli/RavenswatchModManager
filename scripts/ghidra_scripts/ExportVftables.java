// Dump every known C++ vftable + its function-pointer slots to JSON-Lines.
//
// Used to recover virtual-method addresses for hooking, since the
// Ravenswatch PE is stripped and Ghidra recovers vftables from RTTI but
// not the individual virtual method names.
//
// Each line:
//   {"sym":"oe::dt::HeroProgressionUnlockConditionSettings::vftable",
//    "addr":"0x140xxxxxxx",
//    "slots":[ {"i":0,"va":"0x140xxxxxxx","name":"FUN_140xxxxxxx"},
//              {"i":1,"va":"0x140xxxxxxx","name":"FUN_140xxxxxxx"}, ... ]}
//
//@category RSMM
//@runtime Java

import java.io.BufferedWriter;
import java.io.FileWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import ghidra.program.model.symbol.SymbolTable;

public class ExportVftables extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("ExportVftables requires output path");
            return;
        }
        String outPath = args[0];

        SymbolTable symtab = currentProgram.getSymbolTable();
        Memory mem = currentProgram.getMemory();

        int dumped = 0;
        try (BufferedWriter w = new BufferedWriter(new FileWriter(outPath))) {
            SymbolIterator it = symtab.getAllSymbols(true);
            while (it.hasNext()) {
                Symbol s = it.next();
                String name = s.getName(true);
                if (!name.endsWith("::vftable")) continue;
                Address vtaddr = s.getAddress();
                if (vtaddr == null || !mem.contains(vtaddr)) continue;

                StringBuilder slots = new StringBuilder();
                slots.append('[');
                // Walk pointer-sized slots. Stop when the slot value doesn't
                // resolve to a defined function (vtable terminator).
                long ptrSize = currentProgram.getDefaultPointerSize();
                int max = 64; // safety bound
                boolean first = true;
                for (int i = 0; i < max; i++) {
                    Address slotAddr = vtaddr.add(i * ptrSize);
                    long target;
                    try {
                        if (ptrSize == 8) target = mem.getLong(slotAddr);
                        else              target = mem.getInt(slotAddr) & 0xFFFFFFFFL;
                    } catch (Exception ex) { break; }
                    if (target == 0) break;
                    Address tgtAddr;
                    try { tgtAddr = currentProgram.getAddressFactory()
                                       .getDefaultAddressSpace().getAddress(target); }
                    catch (Exception ex) { break; }
                    Function fn = currentProgram.getFunctionManager().getFunctionAt(tgtAddr);
                    if (fn == null) break;
                    if (!first) slots.append(',');
                    first = false;
                    slots.append("{\"i\":").append(i)
                         .append(",\"va\":\"0x").append(Long.toHexString(target))
                         .append("\",\"name\":").append(jsonEscape(fn.getName()))
                         .append('}');
                }
                slots.append(']');

                w.write("{\"sym\":");
                w.write(jsonEscape(name));
                w.write(",\"addr\":\"0x");
                w.write(Long.toHexString(vtaddr.getOffset()));
                w.write("\",\"slots\":");
                w.write(slots.toString());
                w.write("}\n");
                dumped++;
            }
        }
        println("ExportVftables wrote " + dumped + " vftables to " + outPath);
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
