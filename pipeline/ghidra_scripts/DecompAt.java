// Defines functions at given addresses (if missing), decompiles them. Usage: -postScript DecompAt.java <outdir> <addr>...
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.Function;
import java.io.File;
import java.nio.file.Files;

public class DecompAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        File out = new File(a[0]); out.mkdirs();
        DecompInterface d = new DecompInterface(); d.openProgram(currentProgram);
        for (int i = 1; i < a.length; i++) {
            Address ad = toAddr(a[i]);
            Function f = getFunctionAt(ad);
            if (f == null) {
                disassemble(ad);
                f = createFunction(ad, null);
            }
            if (f == null) { println("NOFUNC " + a[i]); continue; }
            var r = d.decompileFunction(f, 60, monitor);
            String c = r.decompileCompleted() ? r.getDecompiledFunction().getC() : "FAILED " + r.getErrorMessage();
            Files.write(new File(out, "NEW_" + ad.toString() + ".c").toPath(), c.getBytes("UTF-8"));
            println("OK " + a[i] + " size=" + f.getBody().getNumAddresses());
        }
    }
}
