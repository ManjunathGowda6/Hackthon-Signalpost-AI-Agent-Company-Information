import base64, sys

if len(sys.argv) < 3:
    print("Usage: file_writer.py <path> <base64>")
    sys.exit(1)
path = sys.argv[1]
b64 = sys.argv[2]
data = base64.b64decode(b64)
with open(path, 'wb') as f:
    f.write(data)
print("Wrote bytes:", len(data))
