"""
Read-only listing of TypeDef/MethodDef names from a managed .NET assembly,
using dnfile's metadata table parsing (no CIL decoding, no execution).

Usage: python list_managed_names.py <path-to-dll> [keyword1 keyword2 ...]
If keywords are given, only prints types/methods whose name contains one
of them (case-insensitive). Otherwise prints everything.

Methods are printed as DeclaringType.MethodName so repeated Unity method
names (FixedUpdate, Update, ...) can be told apart by owning class.
"""

import sys

import dnfile


def type_full_name(row):
    return f"{row.TypeNamespace}.{row.TypeName}" if row.TypeNamespace else row.TypeName


def main():
    if len(sys.argv) < 2:
        print("Usage: python list_managed_names.py <path-to-dll> [keywords...]")
        sys.exit(1)

    path = sys.argv[1]
    keywords = [k.lower() for k in sys.argv[2:]]

    pe = dnfile.dnPE(path)
    tables = pe.net.mdtables

    type_rows = list(tables.TypeDef.rows)

    print(f"== Types (TypeDef) matching {keywords or 'ALL'} ==")
    for row in type_rows:
        full_name = type_full_name(row)
        if not keywords or any(k in full_name.lower() for k in keywords):
            print(full_name)

    print(f"\n== Methods (MethodDef) matching {keywords or 'ALL'}, as DeclaringType.Method ==")
    for ti, row in enumerate(type_rows):
        full_name = type_full_name(row)
        for m in row.MethodList:
            mname = m.row.Name.value if hasattr(m.row.Name, "value") else str(m.row.Name)
            if not keywords or any(k in mname.lower() for k in keywords):
                print(f"{full_name}.{mname}")


if __name__ == "__main__":
    main()
