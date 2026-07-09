# @category RSMM
import os
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
OUT=os.environ.get("RSMM_OUT","/home/ovilli/Documents/Programming/RavenswatchModManager/docs/_re/out_new")
DEC=os.path.join(OUT,"candidates2"); os.path.exists(DEC) or os.makedirs(DEC)
CANDS=[("Entity_ModifyHealth",[0x140392640,0x14039a320,0x14039c420])]
fm=currentProgram.getFunctionManager(); af=currentProgram.getAddressFactory()
di=DecompInterface(); di.openProgram(currentProgram); mon=ConsoleTaskMonitor()
for label,addrs in CANDS:
    for va in addrs:
        fn=fm.getFunctionContaining(af.getAddress("%x"%va))
        if fn is None: print("[RSMM] %s 0x%x no fn"%(label,va)); continue
        res=di.decompileFunction(fn,120,mon)
        body=res.getDecompiledFunction().getC() if res.decompileCompleted() else "// fail"
        p=os.path.join(DEC,"%s__0x%x.c"%(label,va))
        open(p,"w").write("// %s @0x%x entry 0x%x %db\n%s"%(label,va,fn.getEntryPoint().getOffset(),fn.getBody().getNumAddresses(),body))
        print("[RSMM] wrote %s"%p)
