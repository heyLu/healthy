#!/usr/bin/env python3
import os
import sys
import subprocess
import threading
import time

import gi
gi.require_version("GLib", "2.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GLib  # noqa: E402
from gi.repository import Gdk   # noqa: E402
from gi.repository import Gtk   # noqa: E402


PAGE_SIZE = None


class CPUGraph(Gtk.Box):
    def __init__(self, num_samples, name, cpu_usage):
        Gtk.Box.__init__(self)

        self.num_samples = num_samples
        self.name = name
        self.pid = -1
        self.cmdline = None
        self.cpu_usage = cpu_usage
        self.max_cpu = os.cpu_count() * 100

        self.label = Gtk.Label()
        self.label.set_width_chars(20)
        self.label.set_max_width_chars(20)
        self.label.set_single_line_mode(True)

        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_size_request(width=300, height=25)
        self.drawing_area.connect("draw", self.on_draw)

        self.usage_label = Gtk.Label()
        # 4 characters, max is "100%"
        self.usage_label.set_width_chars(4)

        self.pack_start(self.label, True, True, 5)
        self.pack_end(self.usage_label, False, True, 0)
        self.pack_end(self.drawing_area, False, True, 5)

    def update(self):
        self.label.set_label(self.name)
        if self.cmdline:
            self.label.set_tooltip_text(f"{self.pid} - {self.cmdline}")
        else:
            self.label.set_tooltip_text(f"{self.pid}")
        self.usage_label.set_text(f"{int(self.cpu_usage[-1])}%")

        self.drawing_area.set_tooltip_text(f"avg: {int(sum(self.cpu_usage) / len(self.cpu_usage))}%, max: {int(max(self.cpu_usage))}%")

    def on_draw(self, widget, cairo_context):
        style_context = self.get_style_context();
        width, height = self.drawing_area.get_allocated_width(), self.drawing_area.get_allocated_height()

        # background (theme-dependent)
        Gtk.render_background(style_context, cairo_context, 0, 0, width, height)

        scale = 100
        if max(self.cpu_usage) > 100:
            scale = self.max_cpu

        # squiggly lines!
        cairo_context.set_source_rgb(0.3, 0.3, 0.7)
        for idx, cpu in enumerate(self.cpu_usage):
            cairo_context.line_to(idx*(width/self.num_samples), height - cpu*(height/scale))
        cairo_context.stroke()

        return False


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

    def update_graphs(self, cpu_usages):
        for i, cpu_usage in enumerate(cpu_usages):
            self.cpu_graphs[i].name = cpu_usage[0].tcomm
            self.cpu_graphs[i].pid = cpu_usage[0].pid
            self.cpu_graphs[i].cmdline = cpu_usage[0].cmdline
            self.cpu_graphs[i].cpu_usage = cpu_usage[1]

            self.cpu_graphs[i].update()

        GLib.idle_add(self.queue_draw)


class PIDStatsCollector():
    def __init__(self, sample_seconds, update_cpu_fn, update_mem_fn, update_net_fn, update_io_fn):
        self.sample_seconds = sample_seconds
        self.num_samples = int(60 / self.sample_seconds)

        self.update_cpu_fn = update_cpu_fn
        self.update_mem_fn = update_mem_fn
        self.update_net_fn = update_net_fn
        self.update_io_fn = update_io_fn

        self.cpu = {}
        self.mem = {}
        self.net = {}
        self.io = {}

        self.bg_thread = threading.Thread(target=self.update, daemon=True)
        self.bg_thread.start()

    def update(self):
        while True:
            stats = process_stats(self.sample_seconds)

            top_20_cpu = self.collect_top_20(self.cpu, stats, sort_key=lambda stat: stat.cpu_usage)
            GLib.idle_add(self.update_cpu_fn, top_20_cpu)

            top_20_mem = self.collect_top_20(self.mem, stats, sort_key=lambda stat: stat.mem_usage)
            GLib.idle_add(self.update_mem_fn, top_20_mem)

            top_20_net = self.collect_top_20(self.net, stats, sort_key=lambda stat: stat.net_usage)
            GLib.idle_add(self.update_net_fn, top_20_net)

            top_20_io = self.collect_top_20(self.io, stats, sort_key=lambda stat: stat.io_usage)
            GLib.idle_add(self.update_io_fn, top_20_io)

    def collect_top_20(self, per_pid_stats, stats, sort_key=lambda stat: stat.cpu_usage):
        stats.sort(key=sort_key, reverse=True)
        top_20 = stats[:20]

        usages = []
        for pid in top_20:
            if pid not in per_pid_stats:
                per_pid_stats[pid] = [0]*self.num_samples

            per_pid_stats[pid].append(sort_key(pid))
            if len(per_pid_stats[pid]) > self.num_samples:
                per_pid_stats[pid].pop(0)

        for pid in per_pid_stats:
            if pid not in top_20:
                per_pid_stats[pid].append(0)
                if len(per_pid_stats[pid]) > self.num_samples:
                    per_pid_stats[pid].pop(0)

            usages.append((pid, per_pid_stats[pid]))

        usages = list(per_pid_stats.items())
        usages.sort(key=lambda u: sum(u[1]), reverse=True)
        return usages[:20]

class PIDStat():
    def __init__(self, stat_line, statm_line, net_bytes, io_bytes):
        name_start, name_end = stat_line.index('('), stat_line.index(')')
        name = stat_line[name_start+1:name_end]
        stat_line = stat_line[:name_start] + stat_line[name_end+2:]
        fields = stat_line.split()
        fields.insert(1, name)

        self.pid = int(fields[0])
        self.tcomm = fields[1]
        self.utime = int(fields[13])
        self.stime = int(fields[14])

        #self.vsize = int(self.fields[21])
        #self.rss = int(self.fields[22])

        statm_fields = statm_line.split(" ")
        self.size = int(statm_fields[0])
        self.resident = int(statm_fields[1])

        self.receive_bytes = net_bytes[0]
        self.transmit_bytes = net_bytes[1]
        self.net_bytes = net_bytes[0] + net_bytes[1]

        self.read_bytes = io_bytes[0]
        self.write_bytes = io_bytes[1]
        self.io_bytes = io_bytes[0] + io_bytes[1]

        self.cmdline = None
        try:
            with open("/proc/"+fields[0]+"/cmdline", encoding="UTF-8") as f:
                self.cmdline = f.readline().strip().replace("\x00", " ")
        except Exception as ex:
            print("Ignoring", ex)

        self.cpu_usage = 0.0
        self.mem_usage = 0.0
        self.net_usage = 0.0
        self.io_usage = 0.0

    def __repr__(self):
        return f'PIDStat({self.pid}, "{self.tcomm}")'

    def __hash__(self):
        return hash((self.pid, self.tcomm))

    def __eq__(self, other):
        return (self.pid, self.tcomm) == (other.pid, other.tcomm)


# https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/proc.rst
def read_stat(pid):
    try:
        with open("/proc/"+pid+"/stat", encoding="UTF-8") as f:
            stat_line = f.readline().strip()
        with open("/proc/"+pid+"/statm") as f:
            statm_line = f.readline().strip()
        # FIXME: /proc/<pid>/net/dev is per-namespace, not per process,
        #        which is not useful at all on a normal desktop system
        #
        #        as far as i can tell we need root/some capabilities
        #        to get per-process network stats (probably pcap)
        net = read_net_dev("/proc/"+pid+"/net/dev")

        read_bytes = 0
        write_bytes = 0
        try:
            with open("/proc/"+pid+"/io") as f:
                f.readline() # rchar - chars read
                f.readline() # wchar - chars written
                f.readline() # syscr - syscalls read
                f.readline() # syscw - syscalls write
                read_bytes = int(f.readline().strip().split()[1])
                write_bytes = int(f.readline().strip().split()[1])
        except:
            # can't read io usage for non-user processes?
            pass

        return PIDStat(stat_line, statm_line, net, (read_bytes, write_bytes))
    except Exception as ex:
        print("Ignoring", ex)
        # return fake stat that should never appear in stuff
        return PIDStat("-1 (<error>) Z 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0", "0 0 0 0 0 0 0", (0, 0), (0, 0))


def read_global_cpu():
    # user + nice + system + idle + iowait + irq + softirq + steal
    with open("/proc/stat") as f:
        global_stat = [int(x) for x in f.readline().strip()[len("cpu  "):].split()]
        return sum(global_stat[:8])


def read_global_mem():
    # inspired by https://github.com/Alexays/Waybar/blob/600afaf530974c9ef2fec1e61808836712dfde0a/src/modules/memory/common.cpp#L16-L22
    with open("/proc/meminfo") as f:
        mem_total = int(f.readline().strip().split()[1])
        f.readline() # skip mem_free
        mem_avail = int(f.readline().strip().split()[1])
        return (mem_total - mem_avail) * 1024


def read_net_dev(path="/proc/net/dev"):
    # 0       1         2       3    4    5    6     7          8         9        10      11   12   13   14    15      16
	#         Receive                                                    |Transmit
    # iface   bytes     packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    # wlp3s0: 131283187 111770  0    0    0    0     0          0         11322006 90733   0    0    0    0     0       0
    receive_bytes = 0
    transmit_bytes = 0
    with open(path) as f:
        # skip initial two header lines
        f.readline()
        f.readline()
        for line in f.readlines():
            fields = line.strip().split()
            if fields[0] == "lo":
                continue
            receive_bytes += int(fields[1])
            transmit_bytes += int(fields[9])
    return (receive_bytes, transmit_bytes)


# inspired by https://github.com/scaidermern/top-processes/blob/master/top_proc.c
def process_stats(sample_seconds=1.0):
    global_cpu = read_global_cpu()
    net_before = read_net_dev("/proc/net/dev")
    pid_stats_before = dict(((pid, read_stat(pid)) for pid in os.listdir("/proc") if pid.isnumeric()))
    time.sleep(sample_seconds)
    pid_stats_after = dict(((pid, read_stat(pid)) for pid in os.listdir("/proc") if pid.isnumeric()))
    global_cpu = read_global_cpu() - global_cpu
    net_after = read_net_dev("/proc/net/dev")
    global_mem = read_global_mem()

    global_receive_bytes = net_after[0] - net_before[0]
    global_transmit_bytes = net_after[1] - net_before[1]
    global_net_bytes = float(global_receive_bytes + global_transmit_bytes)

    global_io_bytes = sum((stat.io_bytes for stat in pid_stats_after.values())) - sum((stat.io_bytes for stat in pid_stats_before.values()))

    cpu_count = os.cpu_count()

    pid_stats = []
    for pid in pid_stats_after:
        if pid in pid_stats_before:
            pid_before = pid_stats_before[pid]
            pid_after = pid_stats_after[pid]
            cpu_time = (pid_after.utime + pid_after.stime) - (pid_before.utime + pid_before.stime)
            pid_after.cpu_usage = (cpu_time / global_cpu) * 100.0 * cpu_count
            pid_after.mem_usage = ((pid_after.resident * PAGE_SIZE) / global_mem) * 100
            net_bytes = (pid_after.receive_bytes + pid_after.transmit_bytes) - (pid_before.receive_bytes + pid_before.transmit_bytes)
            if global_net_bytes > 0.0:
                pid_after.net_usage = (net_bytes / global_net_bytes) * 100.0
            io_bytes = pid_after.io_bytes - pid_before.io_bytes
            if global_io_bytes > 0.0:
                pid_after.io_usage = (io_bytes / global_io_bytes) * 100.0

            pid_stats.append(pid_after)

    return pid_stats


def on_key_press(widget, event):
    alt = event.state & Gdk.ModifierType.MOD1_MASK
    if alt and event.keyval == Gdk.KEY_1:
        widget.set_current_page(0)
    elif alt and event.keyval == Gdk.KEY_2:
        widget.set_current_page(1)
    elif alt and event.keyval == Gdk.KEY_3:
        widget.set_current_page(2)
    elif alt and event.keyval == Gdk.KEY_4:
        widget.set_current_page(3)


def on_activate(app):
    global PAGE_SIZE
    getconf = subprocess.run(["getconf", "PAGE_SIZE"], capture_output=True)
    PAGE_SIZE = int(getconf.stdout.strip())

    win = Gtk.ApplicationWindow(application=app)
    win.set_keep_above(True)

    sample_seconds = 1.0
    cpu_graphs = CPUGraphCollection(sample_seconds)
    mem_graphs = CPUGraphCollection(sample_seconds)
    net_graphs = CPUGraphCollection(sample_seconds)
    io_graphs = CPUGraphCollection(sample_seconds)
    pid_stats_collector = PIDStatsCollector(sample_seconds,
            cpu_graphs.update_graphs, mem_graphs.update_graphs,
            net_graphs.update_graphs, io_graphs.update_graphs)

    if os.getenv('ONLY_CPU'):
        win.add(cpu_graphs)
    else:
        notebook = Gtk.Notebook()
        notebook.connect("key-press-event", on_key_press)
        notebook.append_page(cpu_graphs, Gtk.Label(label='CPU'))
        notebook.append_page(mem_graphs, Gtk.Label(label='Memory'))
        notebook.append_page(net_graphs, Gtk.Label(label='Network'))
        notebook.append_page(io_graphs, Gtk.Label(label='IO'))
        notebook.foreach(lambda child: notebook.child_set_property(child, "tab-expand", True))
        win.add(notebook)

    win.show_all()


if __name__ == '__main__':
    app = Gtk.Application(application_id='org.papill0n.Healthy')
    app.connect('activate', on_activate)
    app.run(sys.argv)
