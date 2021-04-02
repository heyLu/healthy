#!/usr/bin/env python3
import os
import threading
import time

import gi
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GLib  # noqa: E402
from gi.repository import Gtk   # noqa: E402


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

    def on_draw(self, widget, cairo_context):
        self.label.set_label(self.name)
        if self.cmdline:
            self.label.set_tooltip_text(f"{self.pid} - {self.cmdline}")
        else:
            self.label.set_tooltip_text(f"{self.pid}")
        self.usage_label.set_text(f"{int(self.cpu_usage[-1])}%")

        self.drawing_area.set_tooltip_text(f"avg: {int(sum(self.cpu_usage) / len(self.cpu_usage))}%, max: {int(max(self.cpu_usage))}%")

        style_context = self.get_style_context();
        width, height = self.drawing_area.get_size_request()

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

        self.bg_thread = threading.Thread(target=self.update, daemon=True)
        self.bg_thread.start()

    def update(self):
        while True:
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
                self.cpu_graphs[i].pid = cpu_usage[0].pid
                self.cpu_graphs[i].cmdline = cpu_usage[0].cmdline
                self.cpu_graphs[i].cpu_usage = cpu_usage[1]

            GLib.idle_add(self.queue_draw)


class PIDStat():
    def __init__(self, stat_line):
        name_start, name_end = stat_line.index('('), stat_line.index(')')
        name = stat_line[name_start+1:name_end]
        stat_line = stat_line[:name_start] + stat_line[name_end+2:]
        fields = stat_line.split()
        fields.insert(1, name)

        self.pid = int(fields[0])
        self.tcomm = fields[1]
        self.utime = int(fields[13])
        self.stime = int(fields[14])

        self.cmdline = None
        try:
            with open("/proc/"+fields[0]+"/cmdline", encoding="UTF-8") as f:
                self.cmdline = f.readline().strip().replace("\x00", " ")
        except Exception as ex:
            print("Ignoring", ex)

        self.cpu_usage = 0.0

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
            return PIDStat(stat_line)
    except Exception as ex:
        print("Ignoring", ex)
        # return fake stat that should never appear in stuff
        return PIDStat("-1 (<error>) Z 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0")


def read_global_stat():
    # user + nice + system + idle + iowait + irq + softirq + steal
    with open("/proc/stat") as f:
        global_stat = [int(x) for x in f.readline().strip()[len("cpu  "):].split()]
        return sum(global_stat[:8])


# inspired by https://github.com/scaidermern/top-processes/blob/master/top_proc.c
def cpu_stats(n=20, sample_seconds=1.0):
    global_cpu = read_global_stat()
    pid_stats_before = dict(((pid, read_stat(pid)) for pid in os.listdir("/proc") if pid.isnumeric()))
    time.sleep(sample_seconds)
    pid_stats_after = dict(((pid, read_stat(pid)) for pid in os.listdir("/proc") if pid.isnumeric()))
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
