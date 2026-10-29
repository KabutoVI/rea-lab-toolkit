// Finds defined strings containing a substring, decompiles each function that references them.
// Usage (headless): -postScript StrXrefs.java <outdir> <substring> [substring...]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import java.io.File;
import java.io.PrintWriter;
import java.util.LinkedHashSet;
import java.util.Set;

public class StrXrefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        File out = new File(a[0]); out.mkdirs();
        DecompInterface di = new DecompInterface(); di.openProgram(currentProgram);
        Set<Function> fns = new LinkedHashSet<>();
        DataIterator it = currentProgram.getListing().getDefinedData(true);
        while (it.hasNext()) {
            Data d = it.next();
            Object v = d.getValue();
            if (!(v instanceof String)) continue;
            String s = (String) v;
            for (int i = 1; i < a.length; i++) {
                if (s.contains(a[i])) {
                    println("STR " + d.getAddress() + " \"" + s + "\"");
                    for (Reference r : getReferencesTo(d.getAddress())) {
                        Function f = getFunctionContaining(r.getFromAddress());
                        println("   ref " + r.getFromAddress() + " in " + (f == null ? "-" : f.getName()));
                        if (f != null) fns.add(f);
                    }
                }
            }
        }
        for (Function f : fns) {
            DecompileResults r = di.decompileFunction(f, 60, monitor);
            if (r.decompileCompleted()) {
                try (PrintWriter w = new PrintWriter(new File(out, f.getName() + ".c"), "UTF-8")) { w.println(r.getDecompiledFunction().getC()); }
            }
        }
    }
}
