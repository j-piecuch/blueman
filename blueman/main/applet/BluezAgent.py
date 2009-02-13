# Copyright (C) 2008 Valmantas Paliksa <walmis at balticum-tv dot lt>
# Copyright (C) 2008 Tadas Dailyda <tadas at dailyda dot com>
#
# Licensed under the GNU General Public License Version 3
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# 
import dbus
import dbus.glib
import dbus.service
import os.path
from blueman.Functions import get_icon, dprint
import gtk
import blueman.bluez as Bluez
from blueman.Sdp import *
import gettext
from blueman.Constants import *
_ = gettext.gettext

class AgentErrorRejected(dbus.DBusException):
	def __init__(self):
		dbus.DBusException.__init__(self, name="org.bluez.Error.Rejected")

class AgentErrorCanceled(dbus.DBusException):
	def __init__(self):
		dbus.DBusException.__init__(self, name="org.bluez.Error.Canceled")

class BluezAgent(dbus.service.Object):
	
	def __init__(self, applet, adapter):
		self.applet = applet
		self.adapter = adapter
		self.dialog = None
		self.n = None
		self.bus = dbus.SystemBus();
		adapter_name = os.path.basename(adapter)
		self.dbus_path = "/org/blueman/agent/"+adapter_name
		dbus.service.Object.__init__(self, self.bus, self.dbus_path)
		
		
	def __del__(self):
		dprint("Agent on path", self.dbus_path, "deleted")
	
	@dbus.service.method(dbus_interface="org.bluez.Agent", in_signature="", out_signature="")
	def Release(self):
		dprint("Release")
		self.Cancel()
		self.remove_from_connection()
		self.applet.Agents.remove(self)
	
	def on_notification_close(self, n, action):
		if action != "closed":
			self.dialog.show()
		else:
			if self.dialog:
				self.dialog.response(gtk.RESPONSE_REJECT)
		self.applet.status_icon.set_blinking(False)
		self.n = None
	
	def passkey_dialog_cb(self, dialog, response_id, is_numeric, ok, err):
		if response_id == gtk.RESPONSE_ACCEPT:
			ret = self.pin_entry.get_text()
			if is_numeric:
				ret = int(ret)
			ok(ret)
		else:
			err(AgentErrorRejected())
		dialog.destroy()
		self.dialog = None
	
	def get_device_alias(self, device_path):
		device = Bluez.Device(device_path)
		props = device.GetProperties()
		address = props["Address"]
		name = props["Name"]
		alias = address
		if name:
			alias = "<b>%s</b> (%s)" % (name, address)
		return alias
	
	def passkey_common(self, device_path, dialog_msg, notify_msg, is_numeric, ok, err):
		alias = self.get_device_alias(device_path)
		notify_message = _("Pairing request for %s") % (alias)
		
		if self.dialog:
			dprint("Agent: Another dialog still active, cancelling")
			raise AgentErrorCanceled
		
		self.dialog, self.pin_entry = self.build_passkey_dialog(alias, dialog_msg, is_numeric)
		if not self.dialog:
			dprint("Agent: Failed to build dialog")
			raise AgentErrorCanceled
		
		self.n = self.applet.show_notification(_("Bluetooth device"), notify_message, 20000,
										[["action", notify_msg]], 
										self.on_notification_close, 
										pixbuf=get_icon("gtk-dialog-authentication", 48))
		self.applet.status_icon.set_blinking(True)
		self.dialog.connect("response", self.passkey_dialog_cb, is_numeric, ok, err)
	
	@dbus.service.method(dbus_interface="org.bluez.Agent", in_signature="o", out_signature="s", async_callbacks=("ok","err"))
	def RequestPinCode(self, device, ok, err):
		dprint("Agent.RequestPinCode")
		dialog_msg = _("Enter PIN code for authentication:")
		notify_msg = _("Enter PIN code")
		self.passkey_common(device, dialog_msg, notify_msg, False, ok, err)
		
	@dbus.service.method(dbus_interface="org.bluez.Agent", in_signature="o", out_signature="u", async_callbacks=("ok","err"))
	def RequestPasskey(self, device, ok, err):
		dprint("Agent.RequestPasskey")
		dialog_msg = _("Enter passkey for authentication:")
		notify_msg = _("Enter passkey")
		self.passkey_common(device, dialog_msg, notify_msg, True, ok, err)
	
	@dbus.service.method(dbus_interface="org.bluez.Agent", in_signature="ouy", out_signature="")
	def DisplayPasskey(self, device, passkey, entered):
		pass
	
	def on_confirm_action(self, n, action):
		self.applet.status_icon.set_blinking(False)
		if action == "confirm":
			self.confirm_ok_cb()
		else:
			self.auth_err_cb(AgentErrorRejected())
		self.confirm_ok_cb = None
		self.confirm_err_cb = None
	
	@dbus.service.method(dbus_interface="org.bluez.Agent", in_signature="ou", out_signature="", async_callbacks=("ok","err"))
	def RequestConfirmation(self, device, passkey, ok, err):
		dprint("Agent.RequestConfirmation")
		alias = self.get_device_alias(device)
		notify_message = (_("Pairing request for:")+"\n<b>%s</b>\n"+_("Confirm value for authentication:")+" <b>%s</b>") % (alias, passkey)
		actions = [["confirm", _("Confirm")], ["deny", _("Deny")]]
		
		self.confirm_ok_cb = ok
		self.confirm_err_cb = err
		self.n = self.applet.show_notification(_("Bluetooth device"), notify_message, 20000,
												actions, self.on_confirm_action,
												pixbuf=get_icon("gtk-dialog-authentication", 48))
		self.applet.status_icon.set_blinking(True)
	
	def on_auth_action(self, n, action):
		self.applet.status_icon.set_blinking(False)
		if action == "always":
			device = Bluez.Device(self.auth_dev_path)
			device.SetProperty("Trusted", True)
		if action == "always" or action == "accept":
			self.auth_ok_cb()
		else:
			if self.auth_err_cb:
				self.auth_err_cb(AgentErrorRejected())
		self.auth_dev_path = None
		self.auth_ok_cb = None
		self.auth_err_cb = None
	
	@dbus.service.method(dbus_interface="org.bluez.Agent", in_signature="os", out_signature="", async_callbacks=("ok","err"))
	def Authorize(self, device, uuid, ok, err):
		dprint("Agent.Authorize")
		alias = self.get_device_alias(device)
		uuid16 = uuid128_to_uuid16(uuid)
		service = uuid16_to_name(uuid16)
		notify_message = (_("Authorization request for:")+"\n<b>%s</b>\n"+_("Service:")+" <b>%s</b>") % (alias, service)
		actions = [["always", _("Always accept")],
					["accept", _("Accept")],
					["deny", _("Deny")]]
		
		self.auth_dev_path = device
		self.auth_ok_cb = ok
		self.auth_err_cb = err
		self.n = self.applet.show_notification(_("Bluetooth device"), notify_message, 20000,
												actions, self.on_auth_action,
												pixbuf=get_icon("gtk-dialog-authentication", 48))
		self.applet.status_icon.set_blinking(True)
	
	@dbus.service.method(dbus_interface="org.bluez.Agent", in_signature="s", out_signature="", async_callbacks=("ok","err"))
	def ConfirmModeChange(self, mode, ok, err):
		pass
	
	@dbus.service.method(dbus_interface="org.bluez.Agent", in_signature="", out_signature="")
	def Cancel(self):
		dprint("cancelled")
		if self.dialog:
			self.dialog.response(gtk.RESPONSE_REJECT)
		try:
			self.n.close()
		except:
			pass
			
	def build_passkey_dialog(self, device_alias, dialog_msg, is_numeric):
		def on_insert_text(editable, new_text, new_text_length, position):
			if not new_text.isdigit():
				editable.stop_emission("insert-text")
		
		builder = gtk.Builder()
		builder.add_from_file(UI_PATH +"/applet-passkey.ui")
		builder.set_translation_domain("blueman")
		dialog = builder.get_object("dialog")
		dialog.props.icon_name = "blueman"
		dev_name = builder.get_object("device_name")
		dev_name.set_markup("<b>"+device_alias+"</b>")
		msg = builder.get_object("message")
		msg.set_text(dialog_msg)
		pin_entry = builder.get_object("pin_entry")
		show_input = builder.get_object("show_input_check")
		if (is_numeric):
			pin_entry.set_max_length(6)
			pin_entry.set_width_chars(6)
			pin_entry.connect("insert-text", on_insert_text)
			show_input.hide()
		else:
			pin_entry.set_max_length(16)
			pin_entry.set_width_chars(16)
			pin_entry.set_visibility(False)
		show_input.connect("toggled", lambda x: pin_entry.set_visibility(x.props.active))
		accept_button = builder.get_object("accept")
		pin_entry.connect("changed", lambda x: accept_button.set_sensitive(x.get_text() != ''))
		
		return (dialog, pin_entry)

