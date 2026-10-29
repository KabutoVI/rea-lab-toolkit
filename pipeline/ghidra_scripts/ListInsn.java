// Prints instructions with bytes for a function. Usage: -postScript ListInsn.java <outfile> <addr>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import java.io.*;

public class ListInsn extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        Function f = getFunctionAt(toAddr(a[1]));
        try (PrintWriter w = new PrintWriter(a[0])) {
            for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                StringBuilder b = new StringBuilder();
                for (byte x : i.getBytes()) b.append(String.format("%02x", x & 0xff));
                w.println(i.getAddress() + " " + b + " " + i);
            }
        }
    }
}
