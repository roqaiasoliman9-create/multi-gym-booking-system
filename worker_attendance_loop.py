import time
from worker_attendance import mark_no_show

while True:
    mark_no_show()
    time.sleep(60)