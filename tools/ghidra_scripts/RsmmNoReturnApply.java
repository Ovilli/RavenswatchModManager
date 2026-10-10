// Clear wrong "noreturn" flags, re-flow each call site, regrow the parent
// functions, and fold back tail functions that exist only because the parent
// was cut short.
//
// A function is WRONGLY noreturn when its own body (a thunk's: its target's)
// contains a RET: Ghidra builds the body by following flow, so a RET in it is
// reachable. On the 2026-10-10 build that rule picked exactly free,
// std::_Allocate and both oCString_Dtor entries plus their thunks (12 of 45
// flagged functions) — the flags auto-analysis set, which cut 4,443 functions
// short at their first free. Rule-based, not address-based, so it survives game
// patches; scripts/ghidra_export.py runs it after every auto-analysis.
//
// Args: <log out path> [--list]   (--list reports the targets and changes nothing)
// Saves when run without -readOnly.
// @category RSMM
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.nio.file.*;
import java.util.*;

public class RsmmNoReturnApply extends GhidraScript {
    static final java.util.regex.Pattern NEVER_RETURNS = java.util.regex.Pattern.compile(
        "(?i)throw|terminate|abort|(^|_)exit|failfast|invalid_parameter|report_gsfailure|invoke_watson");

    int dnr(Function f, DecompInterface ifc) {
        DecompileResults r = ifc.decompileFunction(f, 120, monitor);
        if (r == null || r.getDecompiledFunction() == null) return -1;
        return r.getDecompiledFunction().getC().split("does not return", -1).length - 1;
    }

    boolean bodyReturns(Function f) {
        Listing listing = currentProgram.getListing();
        for (Instruction i : listing.getInstructions(f.getBody(), true)) {
            if (i.getFlowType().isTerminal() && i.getMnemonicString().toUpperCase().startsWith("RET")) return true;
        }
        return false;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String out = args[0];
        boolean listOnly = args.length > 1 && args[1].equals("--list");
        StringBuilder log = new StringBuilder();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        Set<Function> targets = new LinkedHashSet<>();
        for (Function f : fm.getFunctions(true)) {
            if (!f.hasNoReturn()) continue;
            Function body = f.isThunk() ? f.getThunkedFunction(true) : f;
            if (body == null || !bodyReturns(body)) continue;
            // A RET after a call that never comes back is dead code, and these
            // are the CRT functions that end that way. _CxxThrowException has a
            // RET after RaiseException; un-flagging it makes every throw site
            // fall through into garbage. Library names come from Ghidra's
            // function ID, so this holds across game patches.
            if (NEVER_RETURNS.matcher(body.getName()).find() || NEVER_RETURNS.matcher(f.getName()).find()) {
                log.append("kept noreturn (never-returns by name) " + f.getName() + "@" + f.getEntryPoint() + "\n");
                continue;
            }
            targets.add(f);
        }
        if (listOnly) {
            for (Function t : targets)
                log.append("target " + t.getName() + "@" + t.getEntryPoint() + " thunk=" + t.isThunk() + "\n");
            log.append("targets " + targets.size() + "\n");
            Files.write(Paths.get(out), log.toString().getBytes());
            println("RSMM_NR_LIST\n" + log);
            return;
        }
        int nrBefore = 0, userNamed = 0;
        for (Function f : fm.getFunctions(true)) {
            if (f.hasNoReturn()) nrBefore++;
            if (f.getSymbol().getSource() == SourceType.USER_DEFINED) userNamed++;
        }
        log.append("functions_before " + fm.getFunctionCount() + " noreturn_before " + nrBefore
                + " user_named_before " + userNamed + "\n");
        for (Function t : targets)
            log.append("target " + t.getName() + "@" + t.getEntryPoint() + " noreturn=" + t.hasNoReturn() + "\n");

        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        long[] samples = {0x140397aa0L, 0x14074b2f0L, 0x1402e6020L};
        Map<Long, String> before = new HashMap<>();
        for (long s : samples) {
            Function f = fm.getFunctionAt(sp.getAddress(s));
            if (f != null) before.put(s, f.getName() + " body=" + f.getBody().getNumAddresses() + " dnr=" + dnr(f, ifc));
        }

        for (Function t : targets) t.setNoReturn(false);

        Set<Function> parents = new LinkedHashSet<>();
        List<Address[]> sites = new ArrayList<>();  // {call, fallthrough}
        for (Function t : targets) {
            for (Reference r : getReferencesTo(t.getEntryPoint())) {
                if (!r.getReferenceType().isCall()) continue;
                Instruction ci = getInstructionAt(r.getFromAddress());
                if (ci == null) continue;
                Address ca = ci.getAddress();
                Address ft = ca.add(ci.getLength());
                if (ci.isFallThroughOverridden()) ci.clearFallThroughOverride();
                Function p = fm.getFunctionContaining(ca);
                if (p != null) parents.add(p);
                clearListing(ca, ca.add(ci.getLength() - 1));
                disassemble(ca);
                if (getInstructionAt(ft) == null) disassemble(ft);
                sites.add(new Address[] {ca, ft});
            }
        }
        log.append("call_sites " + sites.size() + " parent_functions " + parents.size() + "\n");

        // A function whose entry IS a call site's fall-through, referenced by
        // nothing but that fall-through, is the cut-off tail of the caller.
        int folded = 0;
        for (Address[] s : sites) {
            Function tail = fm.getFunctionAt(s[1]);
            if (tail == null) continue;
            Function p = fm.getFunctionContaining(s[0]);
            if (p == null || p.equals(tail)) continue;
            if (tail.getSymbol().getSource() == SourceType.USER_DEFINED) continue;  // never drop a named one
            boolean otherRefs = false;
            for (Reference r : getReferencesTo(s[1])) {
                if (!r.getFromAddress().equals(s[0]) && r.getReferenceType().isFlow() && !r.getReferenceType().isFallthrough()) {
                    otherRefs = true; break;
                }
            }
            if (otherRefs) continue;
            fm.removeFunction(s[1]);
            folded++;
        }
        log.append("tail_functions_folded " + folded + "\n");

        long grow = 0; int fixed = 0, failed = 0;
        for (Function p : parents) {
            long b0 = p.getBody().getNumAddresses();
            try { CreateFunctionCmd.fixupFunctionBody(currentProgram, p, monitor); fixed++; }
            catch (Exception e) { failed++; }
            grow += p.getBody().getNumAddresses() - b0;
        }
        int joined = 0, outside = 0;
        for (Address[] s : sites) {
            Function p = fm.getFunctionContaining(s[0]);
            if (p != null && p.getBody().contains(s[1])) joined++; else outside++;
        }
        log.append("parents_fixed " + fixed + " fixup_failed " + failed + " body_growth_bytes " + grow + "\n");
        log.append("fallthroughs_inside_parent " + joined + " still_outside " + outside + "\n");

        int nrAfter = 0, userAfter = 0;
        for (Function f : fm.getFunctions(true)) {
            if (f.hasNoReturn()) nrAfter++;
            if (f.getSymbol().getSource() == SourceType.USER_DEFINED) userAfter++;
        }
        log.append("functions_after " + fm.getFunctionCount() + " noreturn_after " + nrAfter
                + " user_named_after " + userAfter + "\n");
        for (long s : samples) {
            Function f = fm.getFunctionAt(sp.getAddress(s));
            log.append("sample " + Long.toHexString(s) + " before: " + before.get(s) + " | after: "
                    + (f == null ? "?" : f.getName() + " body=" + f.getBody().getNumAddresses() + " dnr=" + dnr(f, ifc)) + "\n");
        }
        Files.write(Paths.get(out), log.toString().getBytes());
        println("RSMM_NR_APPLY_DONE\n" + log);
    }
}
