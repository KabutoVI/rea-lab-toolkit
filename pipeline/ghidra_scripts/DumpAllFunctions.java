// Dumps decompiled pseudocode for every non-thunk, non-external function into a folder,
// one file per function, plus manifest.json. Usage (headless): -postScript DumpAllFunctions.java <outdir> [threads]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.util.task.ConsoleTaskMonitor;

import java.io.File;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

public class DumpAllFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args[0]);
        out.mkdirs();
        int threads = args.length > 1 ? Integer.parseInt(args[1]) : 6;

        List<Function> fns = new ArrayList<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (!f.isThunk() && !f.isExternal()) {
                fns.add(f);
            }
        }
        println("Functions to decompile: " + fns.size());

        final ThreadLocal<DecompInterface> local = ThreadLocal.withInitial(() -> {
            DecompInterface d = new DecompInterface();
            d.openProgram(currentProgram);
            return d;
        });
        final List<String> manifest = java.util.Collections.synchronizedList(new ArrayList<>());
        final AtomicInteger done = new AtomicInteger();
        final AtomicInteger failed = new AtomicInteger();
        final int total = fns.size();

        ExecutorService pool = Executors.newFixedThreadPool(threads);
        for (final Function f : fns) {
            pool.submit(() -> {
                try {
                    DecompileResults r = local.get().decompileFunction(f, 30, new ConsoleTaskMonitor());
                    String name = f.getName() + "_" + f.getEntryPoint().toString();
                    if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null) {
                        String code = r.getDecompiledFunction().getC();
                        File file = new File(out, "FUN_" + f.getEntryPoint().toString() + ".c");
                        Files.write(file.toPath(), code.getBytes(StandardCharsets.UTF_8));
                        manifest.add("{\"function\":\"" + f.getName() + "\",\"address\":\"0x" + f.getEntryPoint().toString()
                            + "\",\"bytes\":" + f.getBody().getNumAddresses() + ",\"file\":\"" + file.getName() + "\"}");
                    } else {
                        failed.incrementAndGet();
                    }
                } catch (Throwable t) {
                    failed.incrementAndGet();
                }
                int n = done.incrementAndGet();
                if (n % 500 == 0) {
                    println("progress " + n + "/" + total + " failed=" + failed.get());
                }
            });
        }
        pool.shutdown();
        pool.awaitTermination(24, TimeUnit.HOURS);

        try (PrintWriter w = new PrintWriter(new File(out, "manifest.json"), "UTF-8")) {
            w.println("[");
            for (int i = 0; i < manifest.size(); i++) {
                w.println(manifest.get(i) + (i + 1 < manifest.size() ? "," : ""));
            }
            w.println("]");
        }
        println("DONE decompiled=" + manifest.size() + " failed=" + failed.get() + " total=" + total);
    }
}
