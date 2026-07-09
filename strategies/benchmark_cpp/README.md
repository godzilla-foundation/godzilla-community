# benchmark cpp strategy

## build
```bash
cd strategies/benchmark_cpp
mkdir -p build && cd build
cmake ..
make
```

## run
```bash
cd $GODZILLA_ROOT_DIR
python core/python/dev_run.py -l trace strategy -g benchmark -n simple_benchmark_cpp -p strategies/benchmark_cpp/build/benchmark_cpp*.so -c strategies/benchmark_cpp/conf.json
```

The benchmark launcher under `scripts/benchmark` resolves the built `.so`
automatically and is the preferred entry point.
