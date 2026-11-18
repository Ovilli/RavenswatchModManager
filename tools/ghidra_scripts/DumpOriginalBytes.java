// Writes the program's stored original file bytes to the path in script arg 0.
// @category RSMM
import ghidra.app.script.GhidraScript;
import ghidra.program.database.mem.FileBytes;
import java.io.FileOutputStream;
import java.util.List;

public class DumpOriginalBytes extends GhidraScript {
    @Override
    public void run() throws Exception {
        String out = getScriptArgs()[0];
        List<FileBytes> all = currentProgram.getMemory().getAllFileBytes();
        println("file bytes entries: " + all.size());
        FileBytes fb = all.get(0);
        long n = fb.getSize();
        byte[] buf = new byte[(int) n];
        int got = fb.getOriginalBytes(0, buf);
        try (FileOutputStream f = new FileOutputStream(out)) {
            f.write(buf, 0, got);
        }
        println("wrote " + got + " of " + n + " bytes from " + fb.getFilename() + " to " + out);
        println("program sha256: " + currentProgram.getExecutableSHA256());
    }
}
