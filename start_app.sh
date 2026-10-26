#!/data/data/com.termux/files/usr/bin/bash
cd ~
termux-wake-lock

# 1. Kill any old processes
pkill -f app.py
pkill -f auto_fetcher.py
pkill -f run_loop.sh

# 2. Start the Auto-Fetcher silently in the background
nohup python3 auto_fetcher.py > auto_fetcher.log 2>&1 &

# 3. Create a restart loop for Flask
cat << 'LOOP' > run_loop.sh
#!/data/data/com.termux/files/usr/bin/bash
cd ~
while true; do
    python3 app.py >> app.log 2>&1
    sleep 3
done
LOOP

chmod +x run_loop.sh

# 4. Start the Flask loop silently in the background
nohup ./run_loop.sh > /dev/null 2>&1 &

echo "✅ 24/7 Server and Auto-Fetcher are now running in the background!"
echo "You can now lock your phone or close Termux."
echo "To stop them, run: pkill -f run_loop.sh && pkill -f auto_fetcher.py"
