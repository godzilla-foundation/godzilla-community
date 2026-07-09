## Installation Steps 

1.Instaill Miniconda

Switch to root and goto home directory
```bash
sudo su
cd ~
```
Update Dependencies
```bash
apt update && apt upgrade
```
Install 
```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
```

The last choice

"Do you wish to update your shell profile to automatically initialize conda?"

Please input yes (default is no) and then activate
```bash
source ~/.bashrc
```

2.Update bashrc
```bash
nano ~/.bashrc
```
add those two lines in the end:
```bash
export LD_LIBRARY_PATH=~/dev/godzilla-community/core/build:~/dev/godzilla-community/core/python/extensions/mock
export PYTHONPATH=~/dev/godzilla-community/core/python/:~/dev/godzilla-community/core/python/extensions/mock:~/dev/godzilla-community/core/build
```
activate the change
```bash
source ~/.bashrc
```

3.Clone the repository
```bash
cd ~/dev/
git clone https://github.com/godzilla-foundation/godzilla-community.git
```

4.Pre Build
```bash
cd ~/dev/godzilla-community/scripts
bash pre_build.sh
```

5.Build
```bash
cd ~/dev/godzilla-community/core
mkdir build
cd build
cmake ..
make
```

6.Copy exchange extension
```bash
cd ~/dev/godzilla-community/core/extensions/
cp -rf mock/ ~/dev/godzilla-community/core/python/extensions/
```

7.Add user api_key and sec_key
```bash
cd ~/dev/godzilla-community
python core/python/dev_run.py account -s mock add
```
user_id : gz_user1
access_key : x
secret_key : x

8.Launch benchmark services
```bash
cd ~/dev/godzilla-community/scripts/benchmark/
bash run.sh start
```

You should see these 6 service instances:
```text
benchmark_replay_server
benchmark_master
benchmark_ledger
benchmark_md_mock
benchmark_td_mock:benchmark
benchmark_strategy
```

Check them with:
```bash
pm2 ls
```

Raw traces are written under:
```text
scripts/benchmark/traces/raw
```

9.Run analysis
```bash
cd ~/dev/godzilla-community/scripts/benchmark
python3 analysis/summarize_latency.py --raw-dir traces/raw --out-dir analysis/output
```