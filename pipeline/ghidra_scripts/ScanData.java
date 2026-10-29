// Finds 32-bit values anywhere in initialized memory and lists the functions that reference them
// (direct references to the data address, or immediates are covered by ScanImm.java).
// Usage (headless): -postScript ScanData.java <outfile> <hexvalue> [hexvalue...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import java.io.PrintWriter;

public class ScanData extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        try (PrintWriter w = new PrintWriter(a[0], "UTF-8")) {
            for (int i = 1; i < a.length; i++) {
                long v = Long.decode(a[i]);
                byte[] pat = new byte[]{(byte) v, (byte) (v >> 8), (byte) (v >> 16), (byte) (v >> 24)};
                for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
                    if (!b.isInitialized() || b.isExecute()) continue;
                    Address at = b.getStart();
                    while (at != null && at.compareTo(b.getEnd()) <= 0) {
                        Address f = currentProgram.getMemory().findBytes(at, b.getEnd(), pat, null, true, monitor);
                        if (f == null) break;
                        for (Reference r : getReferencesTo(f)) {
                            Function fn = getFunctionContaining(r.getFromAddress());
                            w.println(a[i] + "\tdata " + f + "\tref " + r.getFromAddress() + "\t" + (fn == null ? "-" : fn.getName()));
                        }
                        at = f.add(1);
                    }
                }
            }
        }
    }
}
