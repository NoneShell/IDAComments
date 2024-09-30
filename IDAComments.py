from __future__ import print_function
import ida_idaapi
import ida_kernwin
import ida_idp
import ida_netnode
import idc
import ida_bytes
import ida_hexrays
import ida_nalt
import pickle
from datetime import datetime
import re

title = "Comments"

# def show_warning(msg):
    # ida_kernwin.warning(msg)

class UserAddedComments():
    def __init__(self):
        self.netnode = ida_netnode.netnode()
        self.netnode.create("$ UserAddedComments")
        self.imagebase = ida_nalt.get_imagebase()
        self.load_comments()

    def save_comments(self):
        blob = pickle.dumps(self.comments)
        self.netnode.setblob(blob, 0, 'C')

    def load_comments(self):
        blob = self.netnode.getblob(0, 'C')
        if blob is not None:
            self.comments = pickle.loads(blob)
        else:
            self.comments = {}

    def add_comment(self, ea, cmt_type, comment, line_num=None):
        offset = ea - self.imagebase
        key = (offset, cmt_type, line_num)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        matches = re.search(r"#(\S+)", comment)
        if matches:
            tag = matches.group(1)
        else:
            tag = ""

        comment = re.sub(r"#\S+", "", comment).strip()
        
        if not comment:
            self.comments.pop(key, 0)
        else:
            value = {
                "comment" : comment,
                "timestamp" : timestamp,
                "tag" : tag
            }
            self.comments[key] = value
        self.save_comments()


class UIHooks(ida_kernwin.UI_Hooks):
    def __init__(self, cmt_view):
        ida_kernwin.UI_Hooks.__init__(self)
        self.cmt_view = cmt_view

    def current_widget_changed(self, widget, prev_widget):
        if ida_kernwin.get_widget_title(widget) == title:
            self.cmt_view.Refresh()


class PseudoHooks(ida_hexrays.Hexrays_Hooks):
    def __init__(self, usr_cmt):
        ida_hexrays.Hexrays_Hooks.__init__(self)
        self.usr_cmt = usr_cmt

    def cmt_changed(self, cfunc, loc, cmt):
        self.usr_cmt.add_comment(loc.ea, 'pseudocode', cmt)
        return 0


class DisasmHooks(ida_idp.IDB_Hooks):
    def __init__(self, usr_cmt):
        ida_idp.IDB_Hooks.__init__(self)
        self.usr_cmt = usr_cmt
        self.rebased = False
        
    # hook common and repeatable cmts
    def changing_cmt(self, ea, is_repeatable, new_comment):
        cur_ea = idc.here()
        if cur_ea == ea:
            # solve start_ea problems
            cur = ida_kernwin.get_cursor()
            if (cur != (True, 0, 0)):
                # Fix rebasing bug: Rebase pragram will trigger 'changing_cmt', causing to capture auto cmts at ea.
                if self.rebased:
                    self.rebased = False
                    return 0
                if is_repeatable:
                    self.usr_cmt.add_comment(ea, 'repeatable', new_comment)
                else:
                    self.usr_cmt.add_comment(ea, 'common', new_comment)
        return 0
        
    # hook anterior and posterior cmts
    def extra_cmt_changed(self, ea, line_idx, cmt):
        cur_ea = idc.here()
        if cur_ea == ea:
            cur = ida_kernwin.get_cursor()
            if (cur != (True, 0, 0)):
                if line_idx // 1000 == 1: # line_idx = 1xxx
                    self.usr_cmt.add_comment(ea, 'anterior', cmt, line_num=line_idx % 1000)
                if line_idx // 1000 == 2: # line_idx = 2xxx
                    self.usr_cmt.add_comment(ea, 'posterior', cmt, line_num=line_idx % 1000)
        return 0
        
    # hook Function cmts and repeatable Function cmts
    def changing_range_cmt(self, kind, a, cmt, is_repeatable):
        if is_repeatable:
            self.usr_cmt.add_comment(a.start_ea, 'func_repeatable', cmt)
        else:
            self.usr_cmt.add_comment(a.start_ea, 'func_common', cmt)
        return 0
        
    # program image rebased
    def allsegs_moved(self, info):
        self.rebased = True
        self.usr_cmt.imagebase = ida_nalt.get_imagebase()
        
        
class CommentViewer(ida_kernwin.Choose):
    def __init__(self, usr_cmt):
        self.column_map = ["Address", "Timestamp", "Tag", "Comments", "Type"]
        column_titles = [
            ["Address", 10 | ida_kernwin.Choose.CHCOL_HEX],
            ["Timestamp", 15 | ida_kernwin.Choose.CHCOL_PLAIN],
            ["Tag", 10 | ida_kernwin.Choose.CHCOL_PLAIN],
            ["Comments", 30 | ida_kernwin.Choose.CHCOL_PLAIN],
            ["Type", 15 | ida_kernwin.Choose.CHCOL_PLAIN]
        ]
        ida_kernwin.Choose.__init__(
            self,
            title, 
            column_titles,
            flags = ida_kernwin.Choose.CH_CAN_REFRESH)  # Add closing parenthesis here
        self.usr_cmt = usr_cmt
        self.items = []

    def OnInit(self):
        self.usr_cmt.load_comments()  # load comments again
        self.items = []
        for key, value in self.usr_cmt.comments.items():
            row_data = {
                "Address": hex(key[0] + self.usr_cmt.imagebase),
                "Timestamp": value["timestamp"],
                "Tag": value["tag"],
                "Comments": value["comment"],
                "Type": key[1]
            }
            self.items.append([row_data[col] for col in self.column_map])
        return True

    def OnGetSize(self):
        return len(self.items)

    def OnGetLine(self, n):
        return self.items[n]
        
    def OnRefresh(self, n):
        self.OnInit()
        if self.items:
            return [ida_kernwin.Choose.ALL_CHANGED] + self.adjust_last_item(n)
        return None # call standard refresh

    def OnSelectLine(self, n):
        selected_item = self.items[n]     # for single selection chooser
        addr = int(selected_item[0], 16)
        ida_kernwin.jumpto(addr)


def register_open_action(cmt_view):
    """
    Provide the action that will create the widget
    when the user asks for it.
    """
    class create_widget_t(ida_kernwin.action_handler_t):
        def activate(self, ctx):
            cmt_view.Show()

        def update(self, ctx):
            return ida_kernwin.AST_ENABLE_ALWAYS

    action_name = "UserAddedComments:Show"
    action_shortcut = "Ctrl-Shift-C"
    ida_kernwin.register_action(
        ida_kernwin.action_desc_t(
            action_name,
            title,
            create_widget_t(),
            action_shortcut))
    ida_kernwin.attach_action_to_menu(
        f"View/Open subviews/{title}",
        action_name,
        ida_kernwin.SETMENU_APP)


class my_plugin_t(ida_idaapi.plugin_t):
    flags = ida_idaapi.PLUGIN_HIDE                      # Plugin should not appear in the Edit, Plugins menu.
    wanted_name = "Hook and display user-added comments"
    wanted_hotkey = ""
    comment = "Hook and display user-added comments"
    help = ""
    
    def init(self):
        self.usr_cmt = UserAddedComments()              # Create Comments instance here
        
        self.idb_hook = DisasmHooks(self.usr_cmt)       # Hook disassembly comments(common, repeatable, anterior, posterior cmts)
        self.idb_hook.hook()

        self.ray_hook = PseudoHooks(self.usr_cmt)       # Hook pseudo-code comments(cmts in "F5" pseudo-code view)
        self.ray_hook.hook()
        
        self.cmt_view = CommentViewer(self.usr_cmt)     # Create comment viewer instance
        
        register_open_action(self.cmt_view)             # Register to desktop widget and bind shortcut
        
        self.ui_hook = UIHooks(self.cmt_view)           # Refresh commnets viewer in real time 
        self.ui_hook.hook()
        return ida_idaapi.PLUGIN_KEEP                   # Keep us in the memory

    def run(self, arg):
        #self.cmt_view.Show()
        pass
        
    def term(self):
        self.ui_hook.unhook()
        self.ray_hook.unhook()
        self.idb_hook.unhook()
        return


def PLUGIN_ENTRY():
    return my_plugin_t()