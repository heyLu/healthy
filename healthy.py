import os
import random
import time

import gi
gi.require_version("GLib", "2.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import Gtk

class CPUGraph(Gtk.Box):
    def __init__(self, num_samples, name, cpu_usage):
        Gtk.Box.__init__(self)

        self.num_samples = num_samples
        self.name = name
        self.cmdline = None
        self.cpu_usage = cpu_usage
        self.max_cpu = os.cpu_count() * 100

        self.label = Gtk.Label()
        self.label.set_max_width_chars(20)

        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_size_request(width=300, height=25)
        self.drawing_area.connect("draw", self.on_draw)

        self.usage_label = Gtk.Label()
        # 4 characters, max is "100%"
        self.usage_label.set_width_chars(4)

        self.pack_start(self.label, True, True, 5)
        self.pack_end(self.usage_label, False, True, 0)
        self.pack_end(self.drawing_area, False, True, 5)

    def on_draw(self, widget, cairo_context):
        self.label.set_text(self.name)
        self.label.set_tooltip_text(self.cmdline)
        self.usage_label.set_text(f"{int(self.cpu_usage[-1])}%")

        width, height = self.drawing_area.get_size_request()

        # white background
        cairo_context.set_source_rgb(1, 1, 1)
        cairo_context.rectangle(0, 0, width, height)
        cairo_context.fill()

        scale = 100
        if max(self.cpu_usage) > 100:
            scale = self.max_cpu

        # squiggly lines!
        cairo_context.set_source_rgb(0.3, 0.3, 0.7)
        for idx, cpu in enumerate(self.cpu_usage):
            cairo_context.line_to(idx*(width/self.num_samples), height - cpu*(height/scale))
        cairo_context.stroke()

class CPUGraphCollection(Gtk.Box):
    def __init__(self, sample_seconds):
        Gtk.Box.__init__(self, orientation="vertical")

        self.sample_seconds = sample_seconds
        self.num_samples = int(60 / self.sample_seconds)

        self.cpu_graphs = []
        for _ in range(20):
            cpu_graph = CPUGraph(self.num_samples, "", [0]*self.num_samples)
            self.pack_start(cpu_graph, True, True, 5)
            self.cpu_graphs.append(cpu_graph)

        self.cpu = {}
        GLib.idle_add(self.update)

    def update(self):
        global_cpu = read_global_stat()
        top_20_pids = cpu_stats(self.sample_seconds)
        cpu_usages = []
        for pid in top_20_pids:
            if pid not in self.cpu:
                self.cpu[pid] = [0]*self.num_samples

            self.cpu[pid].append(pid.cpu_usage)
            if len(self.cpu[pid]) > self.num_samples:
                self.cpu[pid].pop(0)

        for pid in self.cpu:
            if pid not in top_20_pids:
                self.cpu[pid].append(0)
                if len(self.cpu[pid]) > self.num_samples:
                    self.cpu[pid].pop(0)

            cpu_usages.append((pid, self.cpu[pid]))

        cpu_usages = list(self.cpu.items())
        cpu_usages.sort(key=lambda u: sum(u[1]), reverse=True)
        cpu_usages = cpu_usages[:20]
        for i, cpu_usage in enumerate(cpu_usages):
            self.cpu_graphs[i].name = cpu_usage[0].tcomm
            self.cpu_graphs[i].cmdline = cpu_usage[0].cmdline
            self.cpu_graphs[i].cpu_usage = cpu_usage[1]
            self.cpu_graphs[i].queue_draw()

        GLib.idle_add(self.update)

class PIDStat():
    def __init__(self, stat_line):
        name_start, name_end = stat_line.index('('), stat_line.index(')')
        name = stat_line[name_start+1:name_end]
        stat_line = stat_line[:name_start] + stat_line[name_end+2:]
        self.fields = stat_line.split(" ")
        self.fields.insert(1, name)

        self.pid = int(self.fields[0])
        self.tcomm = self.fields[1]
        self.utime = int(self.fields[13])
        self.stime = int(self.fields[14])

        self.cmdline = None
        try:
            with open("/proc/"+self.fields[0]+"/cmdline") as f:
                self.cmdline = f.readline().strip()
        except Exception as ex:
            print("Ignoring", ex)

        self.cpu_usage = 0.0

    def __getitem__(self, idx):
        return self.fields[idx]

    def __repr__(self):
        return f'PIDStat({self.pid}, "{self.tcomm}")'

    def __hash__(self):
        return hash((self.pid, self.tcomm))

    def __eq__(self, other):
        return (self.pid, self.tcomm) == (other.pid, other.tcomm)
# https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/proc.rst
def read_stat(pid):
    try:
        with open("/proc/"+pid+"/stat") as f:
            stat_line = f.readline().strip()
            return PIDStat(stat_line)
    except Exception as ex:
        print("Ignoring", ex)
        # return fake stat that should never appear in stuff
        return PIDStat("-1 (<error>) Z 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0")

def read_global_stat():
    # user + nice + system + idle + iowait + irq + softirq + steal
    with open("/proc/stat") as f:
        global_stat = [int(x) for x in f.readline().strip()[len("cpu  "):].split(" ")]
        return sum(global_stat[:8])

# inspired by https://github.com/scaidermern/top-processes/blob/master/top_proc.c
def cpu_stats(n=20, sample_seconds=1.0):
    global_cpu = read_global_stat()
    pid_stats_before = dict([(pid, read_stat(pid)) for pid in os.listdir("/proc") if pid.isnumeric()])
    time.sleep(sample_seconds)
    pid_stats_after = dict([(pid, read_stat(pid)) for pid in os.listdir("/proc") if pid.isnumeric()])
    global_cpu = read_global_stat() - global_cpu

    cpu_count = os.cpu_count()

    pid_stats = []
    for pid in pid_stats_after:
        if pid in pid_stats_before:
            pid_before = pid_stats_before[pid]
            pid_after = pid_stats_after[pid]
            cpu_time = (pid_after.utime + pid_after.stime) - (pid_before.utime + pid_before.stime)
            pid_after.cpu_usage = (cpu_time / global_cpu) * 100.0 * cpu_count

            pid_stats.append(pid_after)

    pid_stats.sort(key=lambda stat: stat.cpu_usage, reverse=True)
    return pid_stats[:20]

def on_activate(app):
    win = Gtk.ApplicationWindow(application=app)
    win.set_keep_above(True)

    cpu_graphs = CPUGraphCollection(0.5)

    win.add(cpu_graphs)
    win.show_all()

if __name__ == '__main__':
    app = Gtk.Application(application_id='org.papill0n.Healthy')
    app.connect('activate', on_activate)
    app.run(None)
