docker run -p 9000:9000 -p 9001:9001 \
  -e "MINIO_ROOT_USER=admin" \
  -e "MINIO_ROOT_PASSWORD=password" \
  -v ~/minio_local_data:/data \
  minio/minio server F:/Evan-F/Projects/Recipe App/data --console-address ":9001"
