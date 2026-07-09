# demo cpp strategy

## build & run
* please build and install core before building this demo
```
cd $GODZILLA_ROOT_DIR/core
mkdir build && make
make install
```
* build demo
```
cd strategies/demo_cpp
mkdir build && cd build
cmake ..
make
```
* run demo
```
cd $GODZILLA_ROOT_DIR
python core/python/dev_run.py -ltrace strategy -n future -p strategies/demo_cpp/build/demo_cpp.cpython-310-x86_64-linux-gnu.so -c strategies/conf.json
```
