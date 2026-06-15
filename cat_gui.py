#!/usr/bin/env python3
"""
cat_gui.py
"""
import argparse, collections, json, math, os, queue, socket, sys, threading, time, datetime
import tkinter as tk
from tkinter import messagebox, ttk

# ── CLI argument parsing ─────────────────────────────────────────────────────
def _parse_args():
    ap = argparse.ArgumentParser(description='CAT GUI Interface', add_help=True)
    ap.add_argument('--freq-font', metavar='PATH', default=None,
                    help='TTF/OTF font file for LO/Tune frequency digit displays')
    ap.add_argument('--gui-font',  metavar='PATH', default=None,
                    help='TTF/OTF font file for all other GUI elements')
    ap.add_argument('--scale', metavar='INT', type=int, default=0,
                    help='Initial scale level (-5..5, default 0)')
    ap.add_argument('--bg', choices=['light','dark'], default='dark',
                    help='Background theme: "light" sets all interface '
                         'backgrounds to #FFECD6, "dark" keeps the default colours')
    ap.add_argument('--full-screen', action='store_true', default=False,
                    help='Start in full-screen mode')
    ap.add_argument('--disable-scale', action='store_true', default=False,
                    help='Hide the HiDPI scale +/- controls and scale level number '
                         '(requires --scale to also be specified)')
    ap.add_argument('--host', metavar='HOST', default=None,
                    help='Server hostname or IP to connect to (must be used together with --port)')
    ap.add_argument('--port', metavar='PORT', type=int, default=None,
                    help='Server port to connect to (must be used together with --host)')
    args=ap.parse_args()
    if args.disable_scale:
        scale_given=any(a=='--scale' or a.startswith('--scale=') for a in sys.argv[1:])
        if not scale_given:
            ap.error('--disable-scale requires --scale to also be specified')
    # --host and --port must be used together
    if (args.host is None) != (args.port is None):
        ap.error('--host and --port must be specified together')
    return args

_ARGS = _parse_args()

# ── TTF path (same directory as this script) ──────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TTF        = os.path.join(_SCRIPT_DIR, 'morgenta_regular.ttf')

# ── Font family names resolved after Tk is up ────────────────────────────────
_FREQ_FONT_FAMILY = None   # font family for frequency digits (LO/Tune)
_GUI_FONT_FAMILY  = None   # font family for all other GUI text

def _load_custom_fonts(root):
    global _FREQ_FONT_FAMILY, _GUI_FONT_FAMILY
    import tkinter.font as tkfont

    def _load(path, tag):
        if not path:
            return None
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            print(f'[font] WARNING: {tag} file not found: {path}')
            return None
        try:
            root.tk.call('font', 'create', f'_custom_{tag}')
        except Exception:
            pass
        try:
            root.tk.call('font', 'configure', f'_custom_{tag}', '-file', path)
            fam = root.tk.call('font', 'configure', f'_custom_{tag}', '-family')
            return fam if fam else None
        except Exception:
            pass
        try:
            import pyglet
            pyglet.font.add_file(path)
        except Exception:
            pass
        stem = os.path.splitext(os.path.basename(path))[0]
        fam = stem.replace('_', ' ').replace('-', ' ').title()
        return fam

    _FREQ_FONT_FAMILY = _load(_ARGS.freq_font, 'freq')
    _GUI_FONT_FAMILY  = _load(_ARGS.gui_font,  'gui')

def _freq_font(size, *modifiers):
    fam = _FREQ_FONT_FAMILY or 'TkDefaultFont'
    return (fam, size) + modifiers if modifiers else (fam, size)

def _gui_font(size, *modifiers):
    fam = _GUI_FONT_FAMILY or 'TkDefaultFont'
    return (fam, size) + modifiers if modifiers else (fam, size)

# ── Colour palette ────────────────────────────────────────────────────────────
C = dict(
    win_bg      = "#060d1e",   # outer window / waterfall background
    panel_bg    = "#0c1525",   # left control panel
    panel_mid   = "#0e1a2e",   # toolbar / dividers
    spec_bg     = "#020810",   # spectrum/AF canvas bg
    btn_gray    = "#182438",   # default button
    btn_grn     = "#0e3018",   # green highlight button face
    btn_grn_fg  = "#22dd44",   # green button text
    btn_red_fg  = "#dd2222",   # red "Exit" text
    btn_sel     = "#1a3c6a",   # selected/active blue button
    btn_sel_fg  = "#50c0ff",   # active text
    text        = "#b8cce8",   # normal
    text_dim    = "#4a6080",   # dim labels
    text_grn    = "#22dd44",   # green text (date, active mode)
    freq_amber  = "#ffb800",   # LO/Tune digits
    grid        = "#121e30",   # grid lines
    grid_text   = "#3a5878",   # grid labels
    trace       = "#18e840",   # spectrum trace
    trace_fill  = "#030d06",   # trace fill
    filter_fill = "#142850",   # IF passband
    filter_edge = "#3060e0",   # IF passband edge
    vfo_line    = "#ff2828",   # VFO line
    smeter_grn  = "#28ee50",
    smeter_red  = "#ff3830",
    peak_bar    = "#22ee44",   # bright green peak bar
    toolbar_wf  = "#ff3030",   # "Waterfall" label red
    toolbar_sp  = "#c8d8f0",   # "Spectrum" label
    sep         = "#1a3050",
)

# ── --bg theme override ──────────────────────────────────────────────────────
if _ARGS.bg == 'light':
    _LIGHT_BG = "#FFECD6"
    for _k in ("win_bg","panel_bg","panel_mid","spec_bg","btn_gray"):
        C[_k] = _LIGHT_BG

MODES    = ["AM","ECSS","FM","LSB","USB","CW","DIG"]
NUM_BINS = 900
AF_BINS  = 600

BANDS = [
    ("160m",1_850_000),("80m",3_700_000),("60m",5_330_000),
    ("40m",7_100_000),("30m",10_120_000),("20m",14_195_000),
    ("17m",18_100_000),("15m",21_200_000),("12m",24_900_000),
    ("10m",28_500_000),("6m",50_100_000),
]

# ── Base geometry constants (at scale=1.0) ────────────────────────────────────
BASE = dict(
    win_w=1520, win_h=870,
    min_w=1100, min_h=720,
    left_w=398,
    spec_h=145,
    af_spec_h=140,
    smeter_w=280, smeter_h=85,
    toolbar_h=20,
    freq_digit_size=26,
    freq_sep_size=26,
    freq_label_size=9,
    btn_font_size=8,
    btn_big_size=11,    # transport symbols
    clock_size=11,
    grid_font_size=7,
    smeter_label_size=6,
    smeter_dbm_size=8,
    peak_size=8,
    filter_label_size=9,
    scale_pct_size=7,
    scale_btn_size=9,
    conn_dot_size=12,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def db_to_rgb(db, dmin=-150.0, dmax=0.0):
    t = max(0.0, min(1.0, (db-dmin)/(dmax-dmin)))
    stops = [(0.00,(4,8,22)),(0.18,(0,0,140)),(0.38,(0,120,200)),
             (0.55,(0,200,0)),(0.73,(230,200,0)),(1.00,(255,20,0))]
    for i in range(len(stops)-1):
        t0,c0 = stops[i]; t1,c1 = stops[i+1]
        if t<=t1 or i==len(stops)-2:
            f=max(0.0,min(1.0,(t-t0)/(t1-t0) if t1>t0 else 0.0))
            return (int(c0[0]+(c1[0]-c0[0])*f),
                    int(c0[1]+(c1[1]-c0[1])*f),
                    int(c0[2]+(c1[2]-c0[2])*f))
    return stops[-1][1]

def nice_step(x):
    if x<=0: return 1
    e=math.floor(math.log10(x)); b=10**e
    for m in (1,2,5,10):
        if b*m>=x-1e-9: return b*m
    return b*10

def scaled(key, sc):
    """Return BASE[key] scaled and rounded to int."""
    return max(1, int(round(BASE[key] * sc)))

# ── networking ────────────────────────────────────────────────────────────────

class Net:
    def __init__(self,app):
        self.app=app; self.sock=None; self.connected=False
        self._lk=threading.Lock()

    def connect(self,host,port):
        try: s=socket.create_connection((host,port),timeout=3)
        except OSError as e: return False,str(e)
        s.settimeout(None); self.sock=s; self.connected=True
        threading.Thread(target=self._rx,daemon=True).start()
        return True,"ok"

    def disconnect(self):
        self.connected=False
        if self.sock:
            try: self.sock.close()
            except: pass
            self.sock=None

    def send(self,obj):
        if not self.connected or not self.sock: return False
        d=(json.dumps(obj)+"\n").encode()
        try:
            with self._lk: self.sock.sendall(d)
            return True
        except OSError:
            self.connected=False
            self.app.q.put({"type":"disconnected"})
            return False

    def _rx(self):
        buf=b""
        while self.connected:
            try: data=self.sock.recv(65536)
            except: break
            if not data: break
            buf+=data
            while b"\n" in buf:
                line,buf=buf.split(b"\n",1)
                line=line.strip()
                if not line: continue
                try: self.app.q.put(json.loads(line.decode()))
                except: pass
        self.connected=False
        self.app.q.put({"type":"disconnected"})

# ── Waterfall canvas ──────────────────────────────────────────────────────────

class WFCanvas(tk.Canvas):
    def __init__(self,master,img_w,af=False,**kw):
        kw.setdefault("bg",C["win_bg"]); kw.setdefault("highlightthickness",0)
        super().__init__(master,**kw)
        self.img_w=img_w; self.rows=collections.deque(); self._img=None
        self.af=af
        self.f0=28_490_000.0; self.f1=28_510_000.0  # updated externally
        self._app=None   # set by App after construction
        # Image item placed at top-left; grid overlay items drawn after (on top)
        self._iid=self.create_image(0,0,anchor="nw")
        self.bind("<Configure>",lambda e:(self._render(),self._draw_overlay()))

    def set_freq_range(self,f0,f1):
        self.f0=f0; self.f1=f1; self._draw_overlay()

    def add_row(self,spectrum,dmin=-150,dmax=0):
        n=len(spectrum)
        if n==0: return
        w=self.img_w; row=bytearray(w*3)
        for x in range(w):
            si=min(int(x*n/w),n-1)
            r,g,b=db_to_rgb(spectrum[si],dmin,dmax)
            row[x*3]=r; row[x*3+1]=g; row[x*3+2]=b
        sc=getattr(self._app,'_sc',1.0) if self._app else 1.0
        lbl_h=max(10,int(round(12*sc)))
        ch=max(self.winfo_height()-lbl_h,1)
        self.rows.appendleft(bytes(row))
        # Keep at most canvas-height rows so history fills exactly the widget
        while len(self.rows)>ch: self.rows.pop()
        self._render()
        self._draw_overlay()

    def _render(self):
        nrows=len(self.rows)
        if nrows==0: return
        cw=max(self.winfo_width(),1)
        ch=max(self.winfo_height(),1)
        src_w=self.img_w

        # Reserve a bottom strip for the frequency axis line/labels so the
        # waterfall image stops above it instead of being drawn underneath
        # (and thus overlapped by) the axis overlay.
        sc=getattr(self._app,'_sc',1.0) if self._app else 1.0
        lbl_h=max(10,int(round(12*sc)))
        avail_h=max(1,ch-lbl_h)

        # Build PPM at native row width, native row count
        hdr=f"P6\n{src_w} {nrows}\n255\n".encode()
        body=b"".join(self.rows)
        try:
            src=tk.PhotoImage(width=src_w,height=nrows,data=hdr+body,format="PPM")
        except tk.TclError: return

        # Scale to canvas width using zoom/subsample (integer ratios only in Tk)
        zx=max(1,round(cw/src_w)) if cw>=src_w else 1
        sx=max(1,round(src_w/cw)) if src_w>cw else 1
        if zx>1: src=src.zoom(zx,1)
        if sx>1: src=src.subsample(sx,1)

        # Position image so its bottom aligns to the top of the reserved
        # axis strip; empty space at top remains canvas bg (black) while
        # filling up.
        y_off=max(0,avail_h-nrows)
        self.coords(self._iid,0,y_off)
        self._img=src
        self.itemconfig(self._iid,image=self._img)

    def _draw_overlay(self):
        """Draw frequency axis grid lines and labels on top of the waterfall image."""
        self.delete("wf_overlay")
        cw=max(self.winfo_width(),1)
        ch=max(self.winfo_height(),1)
        span=self.f1-self.f0
        if span<=0: return
        sc=getattr(self._app,'_sc',1.0) if self._app else 1.0
        gfont=("TkFixedFont",max(6,int(round(7*sc))))
        lbl_h=max(10,int(round(12*sc)))

        step=nice_step(span/12)
        f=math.ceil(self.f0/step)*step
        while f<self.f1:
            x=(f-self.f0)/span*cw
            # Vertical grid line spanning the waterfall image area only
            self.create_line(x,0,x,ch-lbl_h,fill=C["grid"],tags="wf_overlay")
            lbl=f"{f:.0f}" if self.af else f"{f/1000:.0f}"
            # Label drawn in the reserved bottom strip, below the image
            self.create_text(x+2,ch-2,text=lbl,fill=C["grid_text"],
                             anchor="sw",font=gfont,tags="wf_overlay")
            f+=step
        # Horizontal bottom axis line
        self.create_line(0,ch-lbl_h,cw,ch-lbl_h,fill=C["sep"],tags="wf_overlay")

# ── Spectrum canvas ───────────────────────────────────────────────────────────

class SpecCanvas(tk.Canvas):
    DB_MIN=-150.0; DB_MAX=0.0; GRAB=6

    def __init__(self,master,app,show_filter=False,af=False,**kw):
        kw.setdefault("bg",C["spec_bg"]); kw.setdefault("highlightthickness",0)
        super().__init__(master,**kw)
        self.app=app; self.show_filter=show_filter; self.af=af
        self.f0=28_490_000.0; self.f1=28_510_000.0; self.data=[]
        self.drag=None; self._last=0.0
        self.bind("<Configure>",lambda e:self.draw())
        if show_filter:
            self.bind("<Button-1>",self._press)
            self.bind("<B1-Motion>",self._drag)
            self.bind("<ButtonRelease-1>",self._rel)
            self.bind("<Motion>",self._motion)
            self.bind("<MouseWheel>",lambda e:self.app.adj_zoom(1 if e.delta>0 else -1))
            self.bind("<Button-4>",lambda e:self.app.adj_zoom(1))
            self.bind("<Button-5>",lambda e:self.app.adj_zoom(-1))

    def _fx(self,f):
        w=max(self.winfo_width(),1); s=self.f1-self.f0
        return (f-self.f0)/s*w if s else 0
    def _xf(self,x):
        w=max(self.winfo_width(),1)
        return self.f0+x/w*(self.f1-self.f0)
    def _dy(self,db,draw_h=None):
        h=draw_h if draw_h is not None else max(self.winfo_height(),1)
        t=(db-self.DB_MIN)/(self.DB_MAX-self.DB_MIN)
        return h-max(0.0,min(1.0,t))*h

    def update_data(self,f0,f1,spec):
        self.f0=f0; self.f1=f1; self.data=spec; self.draw()

    def draw(self):
        self.delete("all")
        w,h=self.winfo_width(),self.winfo_height()
        if w<2 or h<2: return
        sc = getattr(self.app, '_sc', 1.0)
        gfont = ("TkFixedFont", max(6, int(round(7*sc))))
        # Reserve bottom strip for frequency labels so they don't overlap trace
        lbl_h = max(10, int(round(12*sc)))
        draw_h = h - lbl_h   # usable height for trace / dB grid

        # ── 1. Spectrum trace (drawn FIRST = behind everything) ───────────────
        n=len(self.data)
        if n>=2:
            pts=[]
            for i,db in enumerate(self.data):
                pts.extend([i/(n-1)*w,self._dy(db, draw_h)])
            self.create_polygon(pts+[w,draw_h,0,draw_h],fill=C["trace_fill"],outline="")
            self.create_line(pts,fill=C["trace"],width=1)

        # ── 2. IF filter overlay (behind grid, over trace) ────────────────────
        if self.show_filter:
            ctr=(self.f0+self.f1)/2
            fl=self.app.state["filter_lo"]; fh=self.app.state["filter_hi"]
            x1=self._fx(ctr+fl); x2=self._fx(ctr+fh)
            self.create_rectangle(x1,0,x2,draw_h,fill=C["filter_fill"],
                                  outline="",stipple="gray50")
            self.create_line(x1,0,x1,draw_h,fill=C["filter_edge"],width=1)
            self.create_line(x2,0,x2,draw_h,fill=C["filter_edge"],width=1)
            xc=self._fx(ctr)
            self.create_line(xc,0,xc,draw_h,fill=C["vfo_line"],width=1,dash=(4,3))

        # ── 3. dB grid lines + labels (ON TOP of trace) ───────────────────────
        db_labels=[0,-25,-50,-75,-100,-125,-150]
        for db in db_labels:
            y=self._dy(db, draw_h)
            self.create_line(0,y,w,y,fill=C["grid"])
            self.create_text(2,y+1,text=f"{db} dB" if db==0 else str(db),
                             fill=C["grid_text"],anchor="nw",font=gfont)

        # ── 4. Frequency grid lines + labels (ON TOP of trace) ────────────────
        # Estimate pixel width of widest dB label ("-150", 4 chars) so that
        # X-axis frequency labels don't overlap the Y-axis dB labels on the left.
        _db_lbl_w = max(28, int(round(30 * sc)))
        span=self.f1-self.f0
        if span>0:
            step=nice_step(span/12)
            f=math.ceil(self.f0/step)*step
            while f<self.f1:
                x=self._fx(f)
                self.create_line(x,0,x,draw_h,fill=C["grid"])
                lbl=f"{f:.0f}" if self.af else f"{f/1000:.0f}"
                # Label in the reserved bottom strip — skip labels that would
                # land on top of the dB labels in the left margin.
                if x >= _db_lbl_w:
                    self.create_text(x+2,draw_h+lbl_h-1,text=lbl,fill=C["grid_text"],
                                     anchor="sw",font=gfont)
                f+=step

        # ── 5. Separator line between trace area and label strip ──────────────
        self.create_line(0,draw_h,w,draw_h,fill=C["sep"])

        # ── 6. Green peak/hold line at top (always on top) ───────────────────
        self.create_line(0,2,w,2,fill=C["peak_bar"],width=2)

    def _motion(self,e):
        ctr=(self.f0+self.f1)/2
        x1=self._fx(ctr+self.app.state["filter_lo"])
        x2=self._fx(ctr+self.app.state["filter_hi"])
        if abs(e.x-x1)<=self.GRAB or abs(e.x-x2)<=self.GRAB:
            self.config(cursor="sb_h_double_arrow")
        else: self.config(cursor="crosshair")

    def _press(self,e):
        ctr=(self.f0+self.f1)/2
        x1=self._fx(ctr+self.app.state["filter_lo"])
        x2=self._fx(ctr+self.app.state["filter_hi"])
        if abs(e.x-x1)<=self.GRAB: self.drag="lo"
        elif abs(e.x-x2)<=self.GRAB: self.drag="hi"
        else:
            self.drag=None
            self.app.set_frequency(round(self._xf(e.x)/10)*10)

    def _drag(self,e):
        if not self.drag: return
        ctr=(self.f0+self.f1)/2; off=self._xf(e.x)-ctr
        fl=self.app.state["filter_lo"]; fh=self.app.state["filter_hi"]
        if self.drag=="lo": fl=min(off,fh-50)
        else: fh=max(off,fl+50)
        self.app.state["filter_lo"]=round(fl)
        self.app.state["filter_hi"]=round(fh)
        self.draw()
        now=time.time()
        if now-self._last>0.05:
            self._last=now
            self.app.net.send({"cmd":"set_filter","lo":round(fl),"hi":round(fh)})

    def _rel(self,e):
        if self.drag:
            self.app.net.send({"cmd":"set_filter",
                                "lo":self.app.state["filter_lo"],
                                "hi":self.app.state["filter_hi"]})
        self.drag=None

# ── S-Meter ────────────────────────────────────────────────────────────────────

class SMeter(tk.Canvas):
    LO=-127.0; HI=-33.0; S9=-73.0; AL=165.0; AR=15.0
    MAJOR=[(-121,"1"),(-109,"3"),(-97,"5"),(-85,"7"),(-73,"9"),(-53,"+20"),(-33,"+40")]
    MINOR=[-115,-103,-91,-79,-63,-43]

    def __init__(self,master,**kw):
        kw.setdefault("bg",C["panel_bg"]); kw.setdefault("highlightthickness",0)
        super().__init__(master,**kw)
        self.dbm=self.LO; self.txt="S0"
        self._sc=1.0   # current scale factor, updated by App
        self.bind("<Configure>",lambda e:self._draw())

    def set_value(self,dbm,txt): self.dbm=dbm; self.txt=txt; self._draw()

    def _frac(self,db): return (max(self.LO,min(self.HI,db))-self.LO)/(self.HI-self.LO)
    def _ang(self,f): return self.AL-f*(self.AL-self.AR)
    def _pt(self,cx,cy,r,f):
        a=math.radians(self._ang(f))
        return cx+r*math.cos(a),cy-r*math.sin(a)

    def _draw(self):
        self.delete("all")
        w,h=self.winfo_width(),self.winfo_height()
        if w<30 or h<20: return
        sc=self._sc
        # fonts — scale with sc
        label_fs = max(5, int(round(6*sc)))
        dbm_fs   = max(6, int(round(8*sc)))
        dbm_box_w = max(60, int(round(90*sc)))
        dbm_box_h = max(14, int(round(18*sc)))
        dbm_box_h2= max(12, int(round(16*sc)))

        cx=w/2; cy=h-max(10,int(round(14*sc))); R=min(w*0.46,cy)-3
        if R<8: return
        tick_outer=R-2
        tick_major_inner=R-max(6,int(round(10*sc)))
        tick_minor_inner=R-max(4,int(round(6*sc)))
        tick_label_r=R-max(12,int(round(19*sc)))
        arc_r=R-max(3,int(round(5*sc)))
        arc_w=max(2,int(round(3*sc)))
        needle_w=max(1,int(round(2*sc)))
        pivot_r=max(2,int(round(3*sc)))
        needle_inner=R-max(4,int(round(6*sc)))

        sw=self.AL-self.AR; bb=(cx-R,cy-R,cx+R,cy+R)
        self.create_arc(bb,start=self.AR,extent=sw,style="pieslice",
                        fill="#040c1a",outline="")
        self.create_arc(bb,start=self.AR,extent=sw,style="arc",
                        outline=C["sep"],width=1)
        ar=arc_r; sb=(cx-ar,cy-ar,cx+ar,cy+ar)
        aL=self._ang(0); aS=self._ang(self._frac(self.S9)); aR=self._ang(1)
        self.create_arc(sb,start=aS,extent=aL-aS,style="arc",
                        outline=C["smeter_grn"],width=arc_w)
        self.create_arc(sb,start=aR,extent=aS-aR,style="arc",
                        outline=C["smeter_red"],width=arc_w)
        for db,lbl in self.MAJOR:
            f=self._frac(db)
            col=C["smeter_red"] if db>self.S9 else C["text"]
            x1,y1=self._pt(cx,cy,tick_outer,f)
            x2,y2=self._pt(cx,cy,tick_major_inner,f)
            self.create_line(x1,y1,x2,y2,fill=col,width=max(1,int(round(2*sc))))
            xl,yl=self._pt(cx,cy,tick_label_r,f)
            self.create_text(xl,yl,text=lbl,fill=col,
                             font=_gui_font(label_fs,"bold"))
        for db in self.MINOR:
            f=self._frac(db)
            col=C["smeter_red"] if db>self.S9 else C["text"]
            x1,y1=self._pt(cx,cy,tick_outer,f)
            x2,y2=self._pt(cx,cy,tick_minor_inner,f)
            self.create_line(x1,y1,x2,y2,fill=col,width=1)
        # digital readout
        self.create_rectangle(2,h-dbm_box_h,dbm_box_w,h-2,
                               fill="#0a1820",outline=C["sep"])
        self.create_text(max(3,int(round(5*sc))),h-max(2,int(round(4*sc))),
                         text=f"{self.dbm:.1f} dBm",
                         fill=C["smeter_grn"],
                         font=_gui_font(dbm_fs,"bold"),anchor="sw")
        # needle
        f=self._frac(self.dbm)
        nx,ny=self._pt(cx,cy,needle_inner,f)
        self.create_line(cx,cy,nx,ny,fill=C["vfo_line"],width=needle_w)
        self.create_oval(cx-pivot_r,cy-pivot_r,cx+pivot_r,cy+pivot_r,
                         fill=C["vfo_line"],outline="")

# ── Frequency display ─────────────────────────────────────────────────────────

class FreqDisp(tk.Frame):
    """Large amber LCD-style 9-digit frequency display."""
    ND=9  # digits (without separators)

    def __init__(self,master,app,label="LO A",on_change=None,lo_select_cmd=None,**kw):
        super().__init__(master,bg=C["spec_bg"],**kw)
        self.app=app; self._lbl=[]; self._sep_lbls=[]; self._row_lbl=None
        self.value=28_495_000
        self.on_change=on_change
        self._lo_select_cmd=lo_select_cmd   # callable when label-button clicked
        self._label_text=label

        self._build_widgets()
        self.set_value(self.value,notify=False)

    def _build_widgets(self):
        # clear old
        for w in self.winfo_children(): w.destroy()
        self._lbl=[]; self._sep_lbls=[]
        sc=getattr(self.app,'_sc',1.0)
        digit_fs=max(12,int(round(BASE['freq_digit_size']*sc)))
        sep_fs=max(12,int(round(BASE['freq_sep_size']*sc)))
        lbl_fs=max(7,int(round(BASE['freq_label_size']*sc)))

        lbl_text=getattr(self,'_label_text','LO A')
        if self._lo_select_cmd:
            # Selectable button for LO A / LO B
            self._row_lbl=tk.Button(self,text=lbl_text,
                     bg=C["btn_sel"],fg=C["btn_sel_fg"],
                     font=_gui_font(lbl_fs,"bold"),relief="flat",bd=0,
                     padx=max(2,int(round(3*sc))),pady=0,
                     command=self._lo_select_cmd)
        else:
            self._row_lbl=tk.Label(self,text=lbl_text,
                     bg=C["spec_bg"],fg=C["text_dim"],
                     font=_gui_font(lbl_fs))
        self._row_lbl.grid(row=0,column=0,sticky="w",padx=(6,4))

        # Inner frame holds the digit/separator labels as a group so it can
        # be centered within the expanding column 1, independent of the
        # fixed-position label button in column 0.
        digits_frame=tk.Frame(self,bg=C["spec_bg"])
        digits_frame.grid(row=0,column=1,sticky="")
        self.grid_columnconfigure(0,weight=0)
        self.grid_columnconfigure(1,weight=1)

        # When background is light, amber on light is hard to read — use dark orange
        _is_light = _ARGS.bg == 'light'
        _freq_fg = "#b35000" if _is_light else C["freq_amber"]

        col=0
        for i in range(self.ND):
            if i in (3,6):
                sl=tk.Label(digits_frame,text=",",bg=C["spec_bg"],fg=_freq_fg,
                         font=_freq_font(sep_fs,"bold"),
                         padx=0)
                sl.grid(row=0,column=col,sticky="s",pady=(0,1))
                self._sep_lbls.append(sl); col+=1
            d=tk.Label(digits_frame,text="0",bg=C["spec_bg"],fg=_freq_fg,
                       font=_freq_font(digit_fs,"bold"),
                       width=1,padx=1,pady=0)
            d.grid(row=0,column=col,sticky="nsew")
            d.bind("<MouseWheel>",lambda e,i=i:self._bump(i,1 if e.delta>0 else -1))
            d.bind("<Button-4>",  lambda e,i=i:self._bump(i,1))
            d.bind("<Button-5>",  lambda e,i=i:self._bump(i,-1))
            d.bind("<Button-1>",  lambda e,i=i:self._bump(i,1))
            d.bind("<Button-3>",  lambda e,i=i:self._bump(i,-1))
            d.bind("<Double-Button-1>",self._edit)
            self._lbl.append(d); col+=1

    def rescale(self):
        self._build_widgets()
        self.set_value(self.value,notify=False)

    def _bump(self,idx,d):
        self.set_value(max(0,self.value+d*10**(self.ND-1-idx)),notify=True)

    def set_value(self,hz,notify=True):
        hz=int(max(0,min(hz,10**self.ND-1)))
        self.value=hz; s=f"{hz:0{self.ND}d}"
        for i,ch in enumerate(s): self._lbl[i].config(text=ch)
        if notify:
            (self.on_change or self.app.on_freq_changed)(hz)

    def _edit(self,_=None):
        top=tk.Toplevel(self); top.title("Set Frequency")
        top.configure(bg=C["panel_bg"]); top.transient(self.winfo_toplevel())
        tk.Label(top,text="Frequency (Hz):",bg=C["panel_bg"],
                 fg=C["text"]).pack(padx=12,pady=(12,4))
        var=tk.StringVar(value=str(self.value))
        ent=tk.Entry(top,textvariable=var,width=16,justify="right")
        ent.pack(padx=12,pady=4); ent.select_range(0,"end"); ent.focus_set()
        def apply(_=None):
            try: v=int(float(var.get()))
            except: top.destroy(); return
            self.set_value(v,notify=True); top.destroy()
        ent.bind("<Return>",apply)
        tk.Button(top,text="Set",command=apply,bg=C["btn_gray"],
                  fg=C["text"]).pack(pady=(4,12))

# ── toolbar strip (between RF waterfall and AF area) ─────────────────────────

def _toolbar(parent,rbw="23.4 Hz",avg="2",bg=None,sc=1.0,app=None,box_id="rf"):
    if bg is None: bg=C["panel_mid"]
    h=max(16,int(round(BASE['toolbar_h']*sc)))
    fs=max(6,int(round(8*sc)))
    bar=tk.Frame(parent,bg=bg,height=h)
    bar.pack(side="top",fill="x"); bar.pack_propagate(False)

    def lbl(txt,fg,font=None):
        if font is None: font=_gui_font(fs)
        tk.Label(bar,text=txt,bg=bg,fg=fg,font=font).pack(side="left",padx=max(1,int(round(2*sc))))

    def sep():
        tk.Label(bar,text="──",bg=bg,fg=C["text_dim"],
                 font=_gui_font(max(5,int(round(7*sc))))).pack(side="left")

    # ── Mutually exclusive Waterfall / Spectrum toggle buttons ──────────────
    _wf_state = {"sel": "Waterfall"}   # one mutable cell shared by both closures

    def _make_toggle(name, btn_ref_key):
        def _cmd():
            _wf_state["sel"] = name
            _update_toggle_colors()
            if app:
                # Distinct commands per box and per button
                app.net.send({"cmd": "ui_display",
                               "box": box_id,
                               "view": name.lower()})
        return _cmd

    def _update_toggle_colors():
        sel = _wf_state["sel"]
        for bname, btn in _toggle_btns.items():
            if bname == sel:
                btn.config(bg=C["btn_sel"], fg=C["btn_sel_fg"])
            else:
                btn.config(bg=bg, fg=C["toolbar_wf"] if bname=="Waterfall" else C["toolbar_sp"])

    _toggle_btns = {}
    for t in ["◀◀","◀"]: lbl(t,C["text_dim"])
    sep()
    for name, fg in [("Waterfall", C["toolbar_wf"]), ("Spectrum", C["toolbar_sp"])]:
        b = tk.Button(bar, text=name, bg=bg, fg=fg,
                      activebackground=C["btn_sel"], activeforeground=C["btn_sel_fg"],
                      font=_gui_font(fs), relief="flat", bd=1,
                      padx=max(1,int(round(2*sc))), pady=0,
                      command=_make_toggle(name, name))
        b.pack(side="left", padx=max(1,int(round(2*sc))))
        _toggle_btns[name] = b
        sep()
    # Apply initial colours (Waterfall selected by default)
    _update_toggle_colors()

    for t in ["◀","◀◀"]: lbl(t,C["text_dim"])
    sep()
    lbl(f"RBW {rbw}",C["text_dim"])
    tk.Label(bar,text=avg,bg=C["btn_gray"],fg=C["text"],
             font=_gui_font(fs),width=2,relief="flat").pack(side="left",padx=max(1,int(round(2*sc))))
    lbl("Avg",C["text_dim"]); sep()
    lbl("Zoom",C["text_dim"]); sep()
    lbl("Speed",C["text_dim"])
    return bar

# ── CAT GUI function button helper ──────────────────────────────────────────────

def _fbtn(parent,text,fg=None,bg=None,command=None,sc=1.0,**kw):
    if fg is None: fg=C["btn_sel_fg"]   # match LO A button fg
    if bg is None: bg=C["btn_grn"]
    fs=max(6,int(round(8*sc)))
    # No fixed width/padx — button auto-sizes to contain its label
    b=tk.Button(parent,text=text,bg=bg,fg=fg,
                activebackground=C["btn_sel"],activeforeground=C["btn_sel_fg"],
                font=_gui_font(fs),relief="flat",bd=1,
                command=command or (lambda:None),**kw)
    return b

# ── Main Application ──────────────────────────────────────────────────────────

class App:
    def __init__(self,root):
        self.root=root
        self.root.title("CAT GUI Interface")
        self.root.configure(bg=C["win_bg"])

        try:
            root.tk.call("font","create","_MorgentaLoad","-family","Morgenta Regular")
        except: pass
        try:
            root.option_add("*Font","TkDefaultFont")
        except: pass
        try:
            # Disabled labels use the same dim color as the LO A label
            root.option_add("*Label.disabledForeground",C["text_dim"])
        except: pass

        self.net=Net(self); self.q=queue.Queue()

        self.state=dict(
            lo_freq=28_495_000, lo_b_freq=28_495_000, tune_freq=28_505_000,
            filter_lo=100, filter_hi=600,
            agc="Med", mode="USB",
            rf_gain=20.0, volume=80.0, squelch=-130.0,
            agc_thresh=-100.0,
            zoom=1, sample_rate=192_000.0, running=False,
            nr=False, nbrf=False, nbif=False, afc=False,
            mute=False, notch=False, anotch=False,
            ptt=False,
            user_buttons=[{"label":"","type":"normal"} for _ in range(6)],
            user_btn_state=[False]*6,
        )
        self._sup=False
        # HiDPI / 4K scaling state
        self._scale_level = max(-5, min(5, _ARGS.scale))  # from --scale flag
        self._sc = 1.25 ** self._scale_level  # current visual scale factor
        self._build()
        self._refresh()
        self._clock()
        self.poll()

    # ──────────────────────────────────────────────────────────────────────────
    def _build(self):
        r=self.root
        sc=self._sc

        # Apply initial geometry for the requested --scale, clamped to the
        # screen size so the window can't be created larger than the display
        # (which would crop control rows off-screen).
        screen_w=r.winfo_screenwidth(); screen_h=r.winfo_screenheight()
        init_w=min(scaled('win_w',sc), screen_w)
        init_h=min(scaled('win_h',sc), screen_h)
        r.geometry(f"{init_w}x{init_h}")
        r.minsize(scaled('min_w',sc), scaled('min_h',sc))

        # ── top: RF waterfall + spectrum strip ────────────────────────────────
        top=tk.Frame(r,bg=C["win_bg"])
        top.pack(side="top",fill="both",expand=True)

        self.rf_wf=WFCanvas(top,img_w=NUM_BINS)
        self.rf_wf._app=self
        self.rf_wf.pack(side="top",fill="both",expand=True)

        spec_fr=tk.Frame(top,bg=C["spec_bg"],height=scaled('spec_h',sc))
        spec_fr.pack(side="top",fill="x"); spec_fr.pack_propagate(False)
        self._spec_fr=spec_fr
        self.rf_spec=SpecCanvas(spec_fr,self,show_filter=True)
        self.rf_spec.pack(fill="both",expand=True)

        # ── toolbar between RF and bottom ─────────────────────────────────────
        self._toolbar1_parent=r
        self._toolbar1=_toolbar(r,rbw="23.4 Hz",avg="2",sc=sc,app=self,box_id="rf")

        # ── bottom row: left control panel + right AF ─────────────────────────
        bot=tk.Frame(r,bg=C["win_bg"])
        bot.pack(side="top",fill="both",expand=False)
        self._bot=bot

        self._build_left(bot)
        self._build_right(bot)

        # ── Persistent HiDPI scale +/- control (built once, never destroyed) ──
        self._build_scale_ctrl()
        # Enforce minimum height so no GUI elements vanish
        self.root.after(100, self._update_minsize)
        self.root.after(120, self._sync_bot_height)

    # ── left control panel ────────────────────────────────────────────────────
    def _build_left(self,parent):
        sc=self._sc
        lp=tk.Frame(parent,bg=C["panel_bg"],width=scaled('left_w',sc))
        lp.pack(side="left",fill="y"); lp.pack_propagate(False)
        self._lp=lp

        # ── S-meter row ───────────────────────────────────────────────────────
        sm_row=tk.Frame(lp,bg=C["panel_bg"])
        sm_row.pack(fill="x",padx=max(1,int(round(2*sc))),pady=(max(1,int(round(3*sc))),0))
        self._sm_row=sm_row

        pk_col=tk.Frame(sm_row,bg=C["panel_bg"])
        pk_col.pack(side="left")
        fs_pk=max(6,int(round(8*sc)))
        fs_pk_sm=max(5,int(round(7*sc)))

        def _mk_sm_btn(parent, text, fg, cmd_name, font):
            def _cmd():
                self.net.send({"cmd": cmd_name, "name": text})
            return tk.Button(parent, text=text, bg=C["btn_gray"], fg=fg,
                             activebackground=C["btn_sel"],
                             activeforeground=C["btn_sel_fg"],
                             font=font, relief="flat", bd=1,
                             command=_cmd)

        _mk_sm_btn(pk_col,"Peak",C["btn_grn_fg"],"ui_smeter_btn",
                   _gui_font(fs_pk)).pack(anchor="nw",padx=max(1,int(round(2*sc))),pady=0,fill="x")
        _mk_sm_btn(pk_col,"S-units",C["text_dim"],"ui_smeter_btn",
                   _gui_font(fs_pk_sm)).pack(anchor="w",padx=max(1,int(round(2*sc))),pady=0,fill="x")
        _mk_sm_btn(pk_col,"Squelch",C["text_dim"],"ui_smeter_btn",
                   _gui_font(fs_pk_sm)).pack(anchor="w",padx=max(1,int(round(2*sc))),pady=0,fill="x")

        sm_w=scaled('smeter_w',sc); sm_h=scaled('smeter_h',sc)
        self.smeter=SMeter(sm_row,width=sm_w,height=sm_h)
        self.smeter._sc=sc
        self.smeter.pack(side="left",fill="x",expand=True,
                         padx=(max(1,int(round(2*sc))),max(2,int(round(4*sc)))))

        # ── PTT circular button ───────────────────────────────────────────────
        ptt_size = max(36, int(round(54 * sc)))
        ptt_col = tk.Frame(sm_row, bg=C["panel_bg"])
        ptt_col.pack(side="left", padx=(0, max(2, int(round(4*sc)))))
        self._ptt_canvas = tk.Canvas(ptt_col, width=ptt_size, height=ptt_size,
                                     bg=C["panel_bg"], highlightthickness=0)
        self._ptt_canvas.pack()
        fs_ptt = max(6, int(round(7*sc)))
        self._ptt_size = ptt_size

        def _draw_ptt_btn(active):
            c = self._ptt_canvas
            c.delete("all")
            sz = self._ptt_size
            margin = max(3, int(round(4*sc)))
            fill_color = "#cc1111" if active else "#117711"
            rim_color  = "#ff4444" if active else "#22ee44"
            label_color = "#ffcccc" if active else "#ccffcc"
            c.create_oval(margin, margin, sz-margin, sz-margin,
                          fill=fill_color, outline=rim_color,
                          width=max(2, int(round(3*sc))))
            # Subtle inner highlight
            hi = margin + max(3, int(round(5*sc)))
            c.create_oval(hi, hi, sz-hi, sz-hi,
                          fill="", outline="#cc4444" if active else "#44aa44",
                          width=max(1, int(round(2*sc))))
            c.create_text(sz//2, sz//2, text="PTT",
                          fill=label_color,
                          font=_gui_font(fs_ptt, "bold"))

        self._draw_ptt_btn = _draw_ptt_btn
        _draw_ptt_btn(False)

        def _ptt_click(_evt=None):
            new_state = not self.state.get("ptt", False)
            self.state["ptt"] = new_state
            _draw_ptt_btn(new_state)
            self.net.send({"cmd": "set_ptt", "enabled": new_state})

        self._ptt_canvas.bind("<Button-1>", _ptt_click)
        self._ptt_canvas.config(cursor="hand2")

        # ── Mode buttons + FreqMgr ────────────────────────────────────────────
        mode_row=tk.Frame(lp,bg=C["panel_bg"])
        mode_row.pack(fill="x",padx=max(2,int(round(4*sc))),
                      pady=(max(1,int(round(2*sc))),max(1,int(round(1*sc)))))
        self.mode_btns={}
        fs_mode=max(6,int(round(8*sc)))
        for m in MODES:
            b=tk.Button(mode_row,text=m,width=4,
                        command=lambda mm=m:self._set_mode(mm),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        activebackground=C["btn_sel"],
                        font=_gui_font(fs_mode),relief="flat",bd=1,
                        padx=max(1,int(round(2*sc))),pady=max(1,int(round(1*sc))))
            b.pack(side="left",padx=max(1,int(round(1*sc)))); self.mode_btns[m]=b
        tk.Button(mode_row,text="FreqMgr",bg=C["btn_gray"],fg=C["btn_sel_fg"],
                  font=_gui_font(fs_mode),relief="flat",bd=1,
                  padx=max(2,int(round(3*sc))),pady=max(1,int(round(1*sc))),
                  command=lambda:self.net.send({"cmd":"ui_button","name":"FreqMgr"})
                  ).pack(side="right",padx=max(1,int(round(2*sc))))

        # ── LO + Tune freq displays ───────────────────────────────────────────
        freq_box=tk.Frame(lp,bg=C["spec_bg"],bd=0)
        freq_box.pack(fill="x",padx=max(2,int(round(4*sc))),pady=max(1,int(round(1*sc))))

        # Track which LO is active (A or B) and last band selected per LO
        self._lo_active=tk.StringVar(value="A")
        self._lo_band={"A":None,"B":None}   # last selected band name per LO

        def _select_lo(which):
            self._lo_active.set(which)
            _refresh_lo_btns()
            # Restore the band highlight for this LO
            _refresh_band_highlight()
            # Immediately re-centre on the selected LO frequency, reading
            # directly from the display widget so any pending digit edits
            # are included without waiting for a server round-trip.
            if which=="A":
                hz=self.lo_disp.value if hasattr(self,'lo_disp') else self.state["lo_freq"]
            else:
                hz=self.lo_b_disp.value if hasattr(self,'lo_b_disp') else self.state["lo_b_freq"]
            self._update_rf_view(hz)
            self.root.update_idletasks()
            self.net.send({"cmd":"set_lo","lo":which})

        def _refresh_lo_btns():
            a=self._lo_active.get()
            for w,btn in [("A",self._lo_a_disp._row_lbl),
                          ("B",self._lo_b_disp._row_lbl)]:
                if a==w:
                    btn.config(bg=C["btn_sel"],fg=C["btn_sel_fg"])
                else:
                    btn.config(bg=C["btn_gray"],fg=C["text_dim"])

        def _refresh_band_highlight():
            """Light up the band button that was last used for the current LO."""
            active=self._lo_active.get()
            cur=self._lo_band[active]
            for bname,_bw in self._band_btns.items():
                if bname==cur:
                    self._band_btns[bname].config(bg=C["btn_sel"],fg=C["btn_sel_fg"])
                else:
                    self._band_btns[bname].config(bg=C["btn_gray"],fg=C["btn_sel_fg"])

        # ── freq_box: outer container ─────────────────────────────────────────
        # We use a grid: column 0 = LO/Tune rows (stacked), column 1 = band
        # column spanning all three rows but anchored to the top, so the
        # first band button aligns exactly with the LO A row.
        freq_box.grid_columnconfigure(0,weight=1)
        freq_box.grid_columnconfigure(1,weight=0)

        lo_row=tk.Frame(freq_box,bg=C["spec_bg"])
        lo_row.grid(row=0,column=0,sticky="ew")

        # Left side: LO A display
        self.lo_disp=FreqDisp(lo_row,self,label="LO A",
                              lo_select_cmd=lambda:_select_lo("A"))
        self.lo_disp._label_text="LO A"
        self._lo_a_disp=self.lo_disp
        self.lo_disp.pack(side="left",fill="x",expand=True,padx=max(1,int(round(2*sc))),pady=max(1,int(round(2*sc))))
        self.lo_disp.set_value(self.state["lo_freq"],notify=False)

        # ── Band buttons column — top-aligned to LO A row ─────────────────────
        band_col=tk.Frame(freq_box,bg=C["spec_bg"])
        band_col.grid(row=0,column=1,rowspan=3,sticky="n",
                       padx=max(2,int(round(3*sc))),
                       pady=(max(1,int(round(2*sc))),0))
        fs_band=max(6,int(round(7*sc)))
        btn_w=max(4,int(round(5*sc)))
        self._band_btns={}   # name -> Button

        def _band_select(bname, bfreq):
            active=self._lo_active.get()
            self._lo_band[active]=bname
            _refresh_band_highlight()
            if active=="B":
                self.lo_b_disp.set_value(bfreq,notify=True)
            else:
                self.set_frequency(bfreq)

        for bname,bfreq in BANDS:
            b=tk.Button(band_col,text=bname,width=btn_w,anchor="center",
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        activebackground=C["btn_sel"],activeforeground=C["btn_sel_fg"],
                        font=_gui_font(fs_band),relief="flat",bd=0,highlightthickness=0,
                        pady=0,
                        command=lambda n=bname,f=bfreq:_band_select(n,f))
            b.pack(fill="x",padx=0,pady=(0,max(0,int(round(1*sc)))))
            self._band_btns[bname]=b

        lo_b_row=tk.Frame(freq_box,bg=C["spec_bg"])
        lo_b_row.grid(row=1,column=0,sticky="ew")
        self.lo_b_disp=FreqDisp(lo_b_row,self,label="LO B",
                                on_change=self.on_lo_b_changed,
                                lo_select_cmd=lambda:_select_lo("B"))
        self.lo_b_disp._label_text="LO B"
        self._lo_b_disp=self.lo_b_disp
        self.lo_b_disp.pack(side="left",fill="x",expand=True,padx=max(1,int(round(2*sc))),pady=max(1,int(round(2*sc))))
        self.lo_b_disp.set_value(self.state["lo_b_freq"],notify=False)

        # Apply initial LO button colours
        _refresh_lo_btns()

        tune_row=tk.Frame(freq_box,bg=C["spec_bg"])
        tune_row.grid(row=2,column=0,sticky="ew")
        self.tune_disp=FreqDisp(tune_row,self,label="Tune",on_change=self.on_tune_changed)
        self.tune_disp._label_text="Tune"
        self.tune_disp.pack(side="left",fill="x",expand=True,padx=max(1,int(round(2*sc))),pady=max(1,int(round(2*sc))))
        self.tune_disp.set_value(self.state["tune_freq"],notify=False)

        # ── Volume / AGC Thresh sliders ───────────────────────────────────────
        sv=tk.Frame(lp,bg=C["panel_bg"])
        sv.pack(fill="x",padx=max(3,int(round(6*sc))),
                pady=(max(2,int(round(3*sc))),max(1,int(round(1*sc)))))
        fs_sl=max(6,int(round(8*sc)))
        sl_len=max(100,int(round(180*sc)))
        tk.Label(sv,text="Volume",bg=C["panel_bg"],fg=C["text_dim"],
                 font=_gui_font(fs_sl)).grid(row=0,column=0,sticky="w")
        self.vol_var=tk.DoubleVar(value=self.state["volume"])
        tk.Scale(sv,from_=0,to=100,orient="horizontal",variable=self.vol_var,
                 bg=C["panel_bg"],fg=C["text"],troughcolor=C["btn_gray"],
                 highlightthickness=0,showvalue=0,length=sl_len,
                 command=lambda v:self.net.send({"cmd":"set_volume","value":float(v)})
                 ).grid(row=0,column=1,sticky="ew",padx=max(2,int(round(4*sc))))
        tk.Label(sv,text="AGC Thresh.",bg=C["panel_bg"],fg=C["text_dim"],
                 font=_gui_font(fs_sl)).grid(row=1,column=0,sticky="w")
        self.agct_var=tk.DoubleVar(value=self.state.get("agc_thresh",-100))
        tk.Scale(sv,from_=-140,to=-20,orient="horizontal",variable=self.agct_var,
                 bg=C["panel_bg"],fg=C["text"],troughcolor=C["btn_gray"],
                 highlightthickness=0,showvalue=0,length=sl_len,
                 command=lambda v:self.net.send({"cmd":"set_agc_thresh","value":float(v)})
                 ).grid(row=1,column=1,sticky="ew",padx=max(2,int(round(4*sc))))


        # ── SDR-Device / Soundcard / Bandwidth / Options ──────────────────────
        r1=tk.Frame(lp,bg=C["panel_bg"])
        r1.pack(fill="x",padx=max(2,int(round(4*sc))),pady=(max(1,int(round(2*sc))),max(1,int(round(1*sc)))))
        for t in ["SDR-Device","Soundcard","Bandwidth","Options"]:
            _fbtn(r1,t,sc=sc,
                  command=lambda t=t:self.net.send({"cmd":"ui_button","name":t})
                  ).pack(side="left",padx=max(1,int(round(1*sc))),fill="x",expand=True)

        # ── transport bar ─────────────────────────────────────────────────────
        tb=tk.Frame(lp,bg=C["panel_bg"])
        tb.pack(fill="x",padx=max(2,int(round(4*sc))),pady=max(1,int(round(1*sc))))
        colors={"●":"#cc2020","▶":"#22aa22","⏸":"#aaaa20",
                "■":"#607090","◀◀":"#607090","▶▶":"#607090","∞":"#607090"}
        actions={"●":"rec","▶":"play","⏸":"pause","■":"stop",
                 "◀◀":"rw","▶▶":"ff","∞":"infinite"}
        fs_tp=max(8,int(round(BASE['btn_big_size']*sc)))
        for sym in ["●","▶","⏸","■","◀◀","▶▶","∞"]:
            tk.Button(tb,text=sym,bg=C["btn_gray"],fg=colors[sym],
                      font=_gui_font(fs_tp),relief="flat",bd=1,
                      width=2,pady=0,
                      command=lambda sym=sym:self.net.send({"cmd":"transport","action":actions[sym]})
                      ).pack(side="left",padx=max(1,int(round(1*sc))))

        # ── Start ─────────────────────────────────────────────────────────────
        r3=tk.Frame(lp,bg=C["panel_bg"])
        r3.pack(fill="x",padx=max(2,int(round(4*sc))),pady=max(1,int(round(1*sc))))
        self.start_btn=_fbtn(r3,"Start",sc=sc,command=self._toggle_run)
        self.start_btn.pack(side="left",padx=max(1,int(round(1*sc))),fill="x",expand=True)

        # ── NR / NB RF / NB IF / AFC ──────────────────────────────────────────
        r4=tk.Frame(lp,bg=C["panel_bg"])
        r4.pack(fill="x",padx=max(2,int(round(4*sc))),
                pady=(max(2,int(round(4*sc))),max(1,int(round(1*sc)))))
        self.dsp_btns={}
        fs_dsp=max(6,int(round(8*sc)))
        for t,k in [("NR","nr"),("NB RF","nbrf"),("NB IF","nbif"),("AFC","afc")]:
            b=tk.Button(r4,text=t,command=lambda k=k:self._toggle(k),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        font=_gui_font(fs_dsp),relief="flat",bd=1,
                        padx=max(3,int(round(5*sc))),pady=max(1,int(round(2*sc))))
            b.pack(side="left",padx=max(1,int(round(1*sc)))); self.dsp_btns[k]=b

        # ── Mute / AGC Med / Notch / ANotch ──────────────────────────────────
        r5=tk.Frame(lp,bg=C["panel_bg"])
        r5.pack(fill="x",padx=max(2,int(round(4*sc))),pady=max(1,int(round(1*sc))))
        self.agc_btns={}
        for t,k in [("Mute","mute"),("AGC Med","agcmed"),("Notch","notch"),("ANotch","anotch")]:
            b=tk.Button(r5,text=t,
                        command=lambda k=k,t=t:self._agc_tog(k,t),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        font=_gui_font(fs_dsp),relief="flat",bd=1,
                        padx=max(3,int(round(5*sc))),pady=max(1,int(round(2*sc))))
            b.pack(side="left",padx=max(1,int(round(1*sc)))); self.agc_btns[k]=b

        # ── User-defined buttons (1-3 on the AFC row, 4-6 on the ANotch row,
        #    right-aligned). Labels/types come from the server; can be
        #    "normal" (momentary press) or "push" (push-push/toggle). ──────
        self.user_btns={}
        for i in reversed(range(3)):
            idx=i+1
            b=tk.Button(r4,text=self._user_btn_label(idx),
                        command=lambda idx=idx:self._user_btn_press(idx),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        font=_gui_font(fs_dsp),relief="flat",bd=1,
                        width=7,anchor="center",
                        padx=max(3,int(round(5*sc))),pady=max(1,int(round(2*sc))))
            b.pack(side="right",padx=max(1,int(round(1*sc)))); self.user_btns[idx]=b
        for i in reversed(range(3)):
            idx=i+4
            b=tk.Button(r5,text=self._user_btn_label(idx),
                        command=lambda idx=idx:self._user_btn_press(idx),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        font=_gui_font(fs_dsp),relief="flat",bd=1,
                        width=7,anchor="center",
                        padx=max(3,int(round(5*sc))),pady=max(1,int(round(2*sc))))
            b.pack(side="right",padx=max(1,int(round(1*sc)))); self.user_btns[idx]=b

        # ── Date/time + connect controls (bottom of left panel) ──────────────
        bot_l=tk.Frame(lp,bg=C["panel_bg"])
        bot_l.pack(fill="x",padx=max(2,int(round(4*sc))),
                   pady=(max(4,int(round(8*sc))),max(2,int(round(3*sc)))),side="bottom")
        fs_clk=max(8,int(round(BASE['clock_size']*sc)))
        fs_cr=max(6,int(round(8*sc)))

        # ── Connect controls (host / port / connect / status dot) ────────────
        cr=tk.Frame(bot_l,bg=C["panel_bg"])
        cr.pack(fill="x",anchor="w")
        # Determine if host/port were supplied via CLI flags
        _cli_host = _ARGS.host is not None
        # Always create the StringVars; pre-fill from flags if provided
        self.host_var=tk.StringVar(value=_ARGS.host if _cli_host else "127.0.0.1")
        self.port_var=tk.StringVar(value=str(_ARGS.port) if _cli_host else "50101")
        if not _cli_host:
            # Show editable host/port fields only when not supplied via CLI
            tk.Label(cr,text="Host:",bg=C["panel_bg"],fg=C["text_dim"],
                     font=_gui_font(fs_cr)).pack(side="left",padx=(0,max(1,int(round(2*sc)))))
            tk.Entry(cr,textvariable=self.host_var,width=13,
                     bg=C["btn_gray"],fg=C["text"],insertbackground=C["text"],
                     relief="flat",font=_gui_font(fs_cr)
                     ).pack(side="left",padx=(0,max(2,int(round(4*sc)))))
            tk.Label(cr,text="Port:",bg=C["panel_bg"],fg=C["text_dim"],
                     font=_gui_font(fs_cr)).pack(side="left",padx=(0,max(1,int(round(2*sc)))))
            tk.Entry(cr,textvariable=self.port_var,width=6,
                     bg=C["btn_gray"],fg=C["text"],insertbackground=C["text"],
                     relief="flat",font=_gui_font(fs_cr)
                     ).pack(side="left",padx=(0,max(2,int(round(4*sc)))))
        self.conn_btn=tk.Button(cr,text="Connect",
                                command=self._toggle_connect,
                                bg="#0e2a10",fg=C["btn_grn_fg"],
                                activebackground=C["btn_sel"],
                                font=_gui_font(fs_cr,"bold"),relief="flat",bd=1,
                                padx=max(4,int(round(6*sc))),pady=max(1,int(round(2*sc))))
        self.conn_btn.pack(side="left",padx=max(1,int(round(1*sc))))
        fs_dot=max(9,int(round(BASE['conn_dot_size']*sc)))
        self.conn_status=tk.Label(cr,text="●",bg=C["panel_bg"],fg="#331111",
                                  font=_gui_font(fs_dot))
        self.conn_status.pack(side="left",padx=max(2,int(round(4*sc))))

        # ── Date / time — own row at very bottom of box ───────────────────────
        self.clock_var=tk.StringVar(value="")
        clk_row=tk.Frame(bot_l,bg=C["panel_bg"])
        clk_row.pack(fill="x",anchor="w",pady=(max(1,int(round(2*sc))),0))
        tk.Label(clk_row,textvariable=self.clock_var,bg=C["panel_bg"],
                 fg=C["text_grn"],font=_gui_font(fs_clk,"bold")
                 ).pack(side="left",padx=max(2,int(round(4*sc))))

        # small yellow battery/progress bar at very bottom
        prog=tk.Frame(lp,bg=C["panel_bg"],height=max(4,int(round(6*sc))))
        prog.pack(fill="x",side="bottom")
        tk.Frame(prog,bg="#aaaa00",width=max(8,int(round(12*sc))),
                 height=max(3,int(round(5*sc)))).pack(side="left",pady=1,padx=2)

    # ── right: AF waterfall + spectrum ────────────────────────────────────────
    def _build_right(self,parent):
        sc=self._sc
        rp=tk.Frame(parent,bg=C["spec_bg"])
        rp.pack(side="left",fill="both",expand=True)
        self._rp=rp

        self.af_wf=WFCanvas(rp,img_w=AF_BINS,af=True)
        self.af_wf._app=self
        self.af_wf.pack(side="top",fill="both",expand=True)

        af_sf=tk.Frame(rp,bg=C["spec_bg"],height=scaled('af_spec_h',sc))
        af_sf.pack(side="top",fill="x"); af_sf.pack_propagate(False)
        self._af_sf=af_sf
        self.af_spec=SpecCanvas(af_sf,self,show_filter=False,af=True)
        self.af_spec.pack(fill="both",expand=True)

        self._toolbar2=_toolbar(rp,rbw="5.9 Hz",avg="1",sc=sc,app=self,box_id="af")

    # ── HiDPI scale change ────────────────────────────────────────────────────
    def _build_scale_ctrl(self):
        """Persistent HiDPI +/- scale control.

        Built exactly once and never destroyed, so it can never 'disappear'
        even though _change_scale() destroys/rebuilds most of the rest of
        the GUI. It floats as an overlay in the bottom-right corner of the
        window. Range: -9 .. +9, default 0 (shown centered between the two
        buttons).

        If --disable-scale was passed, this control (buttons and level
        number) is not created at all.
        """
        if _ARGS.disable_scale:
            self._scale_ctrl_fr=None
            self._scale_lbl=None
            self._scale_minus_btn=None
            self._scale_plus_btn=None
            return

        sc=self._sc
        fs=max(7,int(round(BASE['scale_btn_size']*sc)))

        fr=tk.Frame(self.root,bg=C["btn_gray"],bd=1,relief="raised")
        fr.place(relx=1.0,rely=1.0,x=-4,y=-4,anchor="se")
        self._scale_ctrl_fr=fr

        self._scale_minus_btn=tk.Button(
            fr,text="−",bg=C["btn_gray"],fg=C["btn_red_fg"],
            font=_gui_font(fs,"bold"),relief="flat",bd=1,
            width=2,pady=0,command=lambda:self._change_scale(-1))
        self._scale_minus_btn.pack(side="left")

        self._scale_lbl=tk.Label(
            fr,text=str(self._scale_level),bg=C["panel_bg"],
            fg=C["text_dim"],font=_gui_font(fs,"bold"),
            width=3,anchor="center")
        self._scale_lbl.pack(side="left")

        self._scale_plus_btn=tk.Button(
            fr,text="+",bg=C["btn_gray"],fg=C["btn_grn_fg"],
            font=_gui_font(fs,"bold"),relief="flat",bd=1,
            width=2,pady=0,command=lambda:self._change_scale(1))
        self._scale_plus_btn.pack(side="left")

    def _rescale_scale_ctrl(self):
        """Update the font size of the persistent +/- scale control to match sc."""
        if _ARGS.disable_scale: return
        sc=self._sc
        fs=max(7,int(round(BASE['scale_btn_size']*sc)))
        f=_gui_font(fs,"bold")
        self._scale_minus_btn.config(font=f)
        self._scale_lbl.config(font=f)
        self._scale_plus_btn.config(font=f)

    def _update_minsize(self):
        """Compute minimum window size so no GUI element can disappear.

        The bottom panel (_bot) has a fixed natural height determined by its
        children. We measure it after the layout settles, add the toolbar and
        spec strip heights, and apply that as the window's minimum height so
        the waterfall (which uses expand=True) absorbs any spare space but
        never pushes the control rows off-screen.
        """
        self.root.update_idletasks()
        sc = self._sc
        # Fixed-height regions below the waterfall
        spec_h   = scaled('spec_h', sc)
        tb_h     = max(16, int(round(BASE['toolbar_h'] * sc)))
        bot_h    = self._bot.winfo_reqheight()
        bot_w    = self._bot.winfo_reqwidth()
        # Minimum waterfall height (keep it visible but can be small)
        wf_min   = max(40, int(round(60 * sc)))
        min_h    = wf_min + spec_h + tb_h + bot_h + 4
        min_w    = max(scaled('min_w', sc), bot_w)
        self.root.minsize(min_w, min_h)
        return min_w, min_h

    def _sync_bot_height(self):
        """Set _bot's height to the left panel's true required content height.

        lp uses pack_propagate(False) to enforce a fixed width, but that also
        suppresses height reporting to _bot, causing the bottom control area to
        be clipped at higher scale levels.  We work around this by summing the
        requisite heights of lp's packed children and applying that as _bot's
        explicit height, so all controls remain fully visible.
        """
        self.root.update_idletasks()
        lp=self._lp
        total_h=0
        for child in lp.pack_slaves():
            try:
                total_h+=child.winfo_reqheight()
                info=child.pack_info()
                pady=info.get('pady',0)
                if isinstance(pady,(list,tuple)):
                    total_h+=pady[0]+pady[1]
                else:
                    total_h+=int(pady)*2
            except Exception:
                pass
        if total_h>0:
            self._bot.pack_propagate(False)
            self._bot.config(height=total_h)
            self._update_minsize()

    def _change_scale(self,delta):
        """Rebuild the GUI at the new scale factor.

        The +/- buttons themselves live in a persistent overlay
        (see _build_scale_ctrl) that is never destroyed, so they remain
        usable indefinitely. Scale level range is -9..+9, default 0,
        and the current level (not a percentage) is shown in the label
        between the two buttons.
        """
        self._scale_level=max(-5,min(5,self._scale_level+delta))
        self._sc=1.25**self._scale_level
        sc=self._sc

        # Destroy and rebuild left panel and right panel inside _bot
        for child in self._bot.winfo_children():
            child.destroy()

        # Also rebuild top-area fixed-height frames (spec strip)
        self._spec_fr.config(height=scaled('spec_h',sc))

        # Rebuild left and right panels
        self._build_left(self._bot)
        self._build_right(self._bot)

        # Rebuild toolbar1 (between RF strip and bot)
        self._toolbar1.destroy()
        self._toolbar1=_toolbar(self._toolbar1_parent,rbw="23.4 Hz",avg="2",sc=sc,app=self,box_id="rf")
        # Re-pack toolbar1 before _bot
        self._toolbar1.pack(before=self._bot)

        # Update the persistent scale label/buttons to show & match the
        # current scale value/size
        if not _ARGS.disable_scale:
            self._scale_lbl.config(text=str(self._scale_level))
            self._rescale_scale_ctrl()
            # Keep the overlay control on top and re-bring it to front
            self._scale_ctrl_fr.lift()

        # Refresh state colours
        self._refresh()

        # Compute the minimum size required at this scale (this also
        # accounts for everything in the left panel, including the
        # transport buttons and "Full Screen" row, so they can never be
        # clipped off-screen).
        self.root.update_idletasks()
        min_w, min_h = self._update_minsize()

        # Clamp the requested window size to both the natural minimum
        # (so nothing is squeezed/hidden) and the available screen size
        # (so the window manager doesn't crop the bottom rows off-screen).
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        new_w = max(min_w, min(scaled('win_w', sc), screen_w))
        new_h = max(min_h, min(scaled('win_h', sc), screen_h))
        self.root.geometry(f"{new_w}x{new_h}")

        # Re-apply minsize once more after geometry settles, in case
        # widget reflow slightly changed the natural sizes.
        self.root.after(100, self._update_minsize)
        self.root.after(120, self._sync_bot_height)

    # ── control logic ──────────────────────────────────────────────────────────
    def _refresh(self):
        for m,b in self.mode_btns.items():
            if m==self.state["mode"]:
                b.config(bg=C["btn_sel"],fg=C["btn_sel_fg"])
            else:
                b.config(bg=C["btn_gray"],fg=C["btn_sel_fg"])
        for k,b in self.dsp_btns.items():
            on=self.state.get(k,False)
            b.config(bg=C["btn_sel"] if on else C["btn_gray"],
                     fg=C["btn_sel_fg"])
        for k,b in self.agc_btns.items():
            on=(self.state["agc"]=="Med") if k=="agcmed" else self.state.get(k,False)
            b.config(bg=C["btn_sel"] if on else C["btn_gray"],
                     fg=C["btn_sel_fg"])
        # User-defined buttons: refresh label and (for push-push type) the
        # pressed/released highlight.
        for idx,b in self.user_btns.items():
            b.config(text=self._user_btn_label(idx))
            cfg=self._user_btn_cfg(idx)
            if cfg.get("type")=="push":
                on=self._user_btn_state(idx)
                b.config(bg=C["btn_sel"] if on else C["btn_gray"],
                         fg=C["btn_sel_fg"])
            else:
                b.config(bg=C["btn_gray"],fg=C["btn_sel_fg"])
        # PTT button
        if hasattr(self, '_draw_ptt_btn'):
            self._draw_ptt_btn(bool(self.state.get("ptt", False)))

    def _toggle_connect(self):
        if self.net.connected:
            if self.state["running"]:
                self.net.send({"cmd":"stop"})
            self.net.disconnect()
            self._on_disconnected()
        else:
            host=self.host_var.get().strip()
            try: port=int(self.port_var.get().strip())
            except ValueError:
                messagebox.showerror("Connect","Invalid port number"); return
            self.conn_btn.config(text="Connecting…",state="disabled")
            self.root.update_idletasks()
            ok,msg=self.net.connect(host,port)
            if not ok:
                self.conn_btn.config(text="Connect",state="normal")
                messagebox.showerror("Connect",f"Cannot connect to {host}:{port}\n{msg}")
                return
            self.net.send({"cmd":"hello"})
            self.net.send({"cmd":"set_freq","hz":self.state["lo_freq"]})
            self.net.send({"cmd":"set_lo_b_freq","hz":self.state["lo_b_freq"]})
            self.net.send({"cmd":"set_tune_freq","hz":self.state["tune_freq"]})
            self.net.send({"cmd":"set_mode","mode":self.state["mode"]})
            self.net.send({"cmd":"start"})
            self.state["running"]=True
            self.conn_btn.config(text="Disconnect",state="normal",
                                 bg="#2a0e0e",fg=C["btn_red_fg"])
            self.conn_status.config(fg=C["btn_grn_fg"])
            self.start_btn.config(text="Stop",bg="#6a1414",fg=C["btn_red_fg"])

    def _on_disconnected(self):
        self.state["running"]=False
        self.conn_btn.config(text="Connect",state="normal",
                             bg="#0e2a10",fg=C["btn_grn_fg"])
        self.conn_status.config(fg="#331111")
        self.start_btn.config(text="Start",bg=C["btn_grn"],fg=C["btn_grn_fg"])

    def _set_mode(self,m):
        self.state["mode"]=m
        defs={"LSB":(-2800,-100),"USB":(100,2800),"AM":(-4500,4500),
              "FM":(-8000,8000),"CW":(300,700)}
        lo,hi=defs.get(m,(self.state["filter_lo"],self.state["filter_hi"]))
        self.state["filter_lo"]=lo; self.state["filter_hi"]=hi
        self._refresh(); self.net.send({"cmd":"set_mode","mode":m})

    def _toggle(self,k):
        self.state[k]=not self.state.get(k,False); self._refresh()
        cmd={"nr":"set_nr","nbrf":"set_nbrf","nbif":"set_nbif","afc":"set_afc"}.get(k)
        if cmd:
            self.net.send({"cmd":cmd,"enabled":self.state[k]})

    def _agc_tog(self,k,t):
        if k=="agcmed":
            self.state["agc"]="Med" if self.state["agc"]!="Med" else "Off"
            self.net.send({"cmd":"set_agc","mode":self.state["agc"]})
        elif k in self.state:
            self.state[k]=not self.state[k]
            cmd={"mute":"set_mute","notch":"set_notch","anotch":"set_anf"}.get(k)
            if cmd:
                self.net.send({"cmd":cmd,"enabled":self.state[k]})
        self._refresh()

    # ── user-defined buttons (server-configured, indices 1..6) ─────────────
    def _user_btn_cfg(self,idx):
        """Return {"label":..., "type":...} for user button idx (1..6),
        falling back to a default if the server hasn't provided one yet."""
        ub=self.state.get("user_buttons") or []
        if 1<=idx<=len(ub) and ub[idx-1]:
            cfg=ub[idx-1]
            return {"label":cfg.get("label",""),"type":cfg.get("type","normal")}
        return {"label":"","type":"normal"}

    def _user_btn_label(self,idx):
        label=self._user_btn_cfg(idx).get("label","").strip()
        # Show empty string when server has not provided a label
        return label[:7]

    def _user_btn_state(self,idx):
        st=self.state.get("user_btn_state") or []
        if 1<=idx<=len(st):
            return bool(st[idx-1])
        return False

    def _user_btn_press(self,idx):
        cfg=self._user_btn_cfg(idx)
        if cfg.get("type")=="push":
            new_on=not self._user_btn_state(idx)
            st=self.state.get("user_btn_state")
            if not st or len(st)<6:
                st=[False]*6
            st[idx-1]=new_on
            self.state["user_btn_state"]=st
            self.net.send({"cmd":"user_button","index":idx,"enabled":new_on})
        else:
            self.net.send({"cmd":"user_button","index":idx})
        self._refresh()

    def _toggle_run(self):
        if not self.net.connected: return
        if self.state["running"]:
            self.net.send({"cmd":"stop"}); self.state["running"]=False
            self.start_btn.config(text="Start",bg=C["btn_grn"],fg=C["btn_grn_fg"])
        else:
            self.net.send({"cmd":"start"}); self.state["running"]=True
            self.start_btn.config(text="Stop",bg="#6a1414",fg=C["btn_red_fg"])

    def adj_zoom(self,d):
        z=int(self.state["zoom"])
        z=min(32,z*2) if d>0 else max(1,z//2)
        self.state["zoom"]=z; self.net.send({"cmd":"set_zoom","value":z})

    def _update_rf_view(self,hz):
        """Re-centre the upper spectrum/waterfall frequency scale on hz."""
        sr = self.state.get("sample_rate", 192_000.0)
        half = sr / 2.0
        f0=hz-half; f1=hz+half
        self.rf_spec.f0=f0; self.rf_spec.f1=f1; self.rf_spec.draw()
        self.rf_wf.set_freq_range(f0,f1)

    def on_freq_changed(self,hz):
        self.state["lo_freq"]=hz
        # Re-centre upper spectrum/waterfall only if LO A is the active LO
        if self._lo_active.get()=="A":
            self._update_rf_view(hz)
        if not self._sup: self.net.send({"cmd":"set_freq","hz":hz})

    def on_lo_b_changed(self,hz):
        self.state["lo_b_freq"]=hz
        # Re-centre upper spectrum/waterfall only if LO B is the active LO
        if self._lo_active.get()=="B":
            self._update_rf_view(hz)
        if not self._sup: self.net.send({"cmd":"set_lo_b_freq","hz":hz})

    def on_tune_changed(self,hz):
        self.state["tune_freq"]=hz
        if not self._sup: self.net.send({"cmd":"set_tune_freq","hz":hz})

    def set_frequency(self,hz):
        hz=int(max(0,hz))
        self.lo_disp.set_value(hz,notify=False); self.on_freq_changed(hz)

    def _clock(self):
        now=datetime.datetime.now()
        h12=now.strftime("%-I") if os.name!="nt" else now.strftime("%#I")
        ampm="a.m." if now.hour<12 else "p.m."
        try:
            self.clock_var.set(
                now.strftime(f"%#d/%#m/%Y  {h12}:%M:%S {ampm}")
                if os.name=="nt"
                else f"{now.day}/{now.month}/{now.year}  {h12}:{now.strftime('%M:%S')} {ampm}"
            )
        except Exception:
            self.clock_var.set(now.strftime("%d/%m/%Y  %H:%M:%S"))
        self.root.after(1000,self._clock)

    # ── network poll ──────────────────────────────────────────────────────────
    def poll(self):
        try:
            for _ in range(100):
                msg=self.q.get_nowait(); self._handle(msg)
        except queue.Empty: pass
        self.root.after(30,self.poll)

    def _handle(self,msg):
        t=msg.get("type")
        if t=="disconnected": self._on_disconnected()
        elif t=="data":
            f0=msg["f_start"]; f1=msg["f_stop"]
            self.rf_spec.update_data(f0,f1,msg["spectrum"])
            self.rf_wf.set_freq_range(f0,f1)
            self.rf_wf.add_row(msg["spectrum"])
            ar=msg.get("af_range",3000)
            self.af_spec.update_data(0,ar,msg["af_spectrum"])
            self.af_wf.set_freq_range(0,ar)
            self.af_wf.add_row(msg["af_spectrum"])
            self.smeter.set_value(msg["smeter_dbm"],msg["smeter_text"])
        if "state" in msg:
            self.state.update(msg["state"]); self._refresh()

# ── entry point ───────────────────────────────────────────────────────────────

def main():
    root=tk.Tk()
    _load_custom_fonts(root)
    app=App(root)
    # Show initial scale level in the overlay label
    if not _ARGS.disable_scale:
        app._scale_lbl.config(text=str(app._scale_level))
    # Apply --full-screen flag
    if _ARGS.full_screen:
        root.attributes("-fullscreen", True)

    # Triple-Esc toggles fullscreen (3 presses within 1 second)
    _esc_times = []
    def _on_esc(event=None):
        import time as _time
        now = _time.monotonic()
        _esc_times.append(now)
        # Keep only presses within the last 1 second
        while _esc_times and now - _esc_times[0] > 1.0:
            _esc_times.pop(0)
        if len(_esc_times) >= 3:
            _esc_times.clear()
            current = bool(root.attributes("-fullscreen"))
            root.attributes("-fullscreen", not current)
    root.bind("<Escape>", _on_esc)

    root.protocol("WM_DELETE_WINDOW",
                  lambda:(app.net.disconnect(), root.destroy()))
    root.mainloop()

if __name__=="__main__":
    main()
