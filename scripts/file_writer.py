import sys, base64

if len(sys.arvv) < 3:
    print("Usage: file_writer.py <path> <base64-content>")
    sys.exit(1)


arg_path = sys.argv[1]
arg_b64 = sys.argv[2]
data = base64.b64decode(arg_b64)
with open(arg_path, 'wb') as f:
    f.write(data)
print(f"Wrote {len(data}s bytes to {arg_path–}")
