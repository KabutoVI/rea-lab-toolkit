// Lists every instruction with a scalar operand equal to one of the given values, with its function.
// Usage (headless): -postScript ScanImm.java <outfile> <value> [value...]   (values hex or decimal)
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;

import java.io.PrintWriter;
import java.util.HashSet;
import java.util.Set;

public class ScanImm extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        Set<Long> vals = new HashSet<>();
        for (int i = 1; i < a.length; i++) vals.add(Long.decode(a[i]));
        try (PrintWriter w = new PrintWriter(a[0], "UTF-8")) {
            InstructionIterator it = currentProgram.getListing().getInstructions(true);
            while (it.hasNext()) {
                Instruction ins = it.next();
                for (int op = 0; op < ins.getNumOperands(); op++) {
                    for (Object o : ins.getOpObjects(op)) {
                        if (o instanceof Scalar && vals.contains(((Scalar) o).getUnsignedValue())) {
                            Function f = getFunctionContaining(ins.getAddress());
                            w.println(ins.getAddress() + "\t" + (f == null ? "-" : f.getName()) + "\t" + ins);
                        }
                    }
                }
            }
        }
    }
}
