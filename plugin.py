# Manage Synology Surveillane Station
# $Id: plugin.py 127 2020-04-11 17:20:56Z eric $
#

"""
<plugin key="SurveillanceStation" name="Synology Surveillance Station Plugin" author="Morand" version="1.0.1" wikilink="" externallink="">
    <description>
        <h2>Synology Surveillance Station</h2><br/>
            Manage Cameras and home mode for Synology Surveillance Station.
            NEED Domoticz 4.9788 or higher and python 3.
        <h3>Parameters</h3><br />
        <ul>
          <li>Address: IP of Synology NVR</li>
          <li>Port: Port of Synology NVR</li>
          <li>Username: Username for Synology NVR access</li>
          <li>Password: Password for Synology NVR access</li>
          <li>Camera Port: IP port where plugin wait to give to domoticz synology snapshots</li>
          <li>SID refresh: time between SID renewal. Value is Polling interval x SID refresh seconds. If Polling interval is set to 0, 10 x SID refresh seconds.</li>
          <li>Polling interval: time between two status requests for HomeMode. If you don't want so synchronize with Synology Homemode, set to 0</li>
        </ul>
   </description>
    <params>
      <param field="Address" label="Address" width="150px" default=''/>
      <param field="Port" label="Port" width="50px" default='5000'/>
      <param field="Username" label="Username" width="150px" />
      <param field="Password" label="Password" width="150px" />
      <param field="Mode1" label="Camera Port" width="50px" default="8585"/>
      <param field="Mode2" label="SID refresh" width="50px" default="30"/>
      <param field="Mode5" label="Polling interval" width="150px" default='10'/>
      <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="True" value="Debug"/>
                <option label="False" value="Normal"  default="true" />
            </options>
       </param>
    </params>
</plugin>
"""

import Domoticz
import sys
import os
sys.path.append('/usr/lib/python3/dist-packages')
import requests
import urllib
import json
import sqlite3
from urllib.parse import urlparse

class  Camera:
    def __init__(self,cam):
        self._id=cam['id']
        self._name=cam['detailInfo']['camName']
        self._snapShotPath='http://'+cam['dsIp']+':'+str(cam['dsPort'])+'/'+'&'.join(cam['snapshot_path'].split('&')[:-2])
        Domoticz.Log('Camera %s (%s): %s'%(self._name,self._id,self._snapShotPath))

    def updateStatus(self,status):
        if Devices[(self._id+1)].sValue != status:
            if status=="On":
                nv=1
            else :
                nv=0
            Domoticz.Log("%s is going to %s"%(self.getName(),status))
            Devices[(self._id+1)].Update(sValue=status,nValue=nv)
            
    def getId(self):
        return self._id

    def getName(self):
        return  self._name
    
    def getSnapShot(self,sid):
        Domoticz.Debug("SnapShot: %s"%(self._snapShotPath+sid))
        r=requests.get(self._snapShotPath+sid,timeout=5)
        return r.content
        
class SID:
    def __init__(self,baseURL,username,password):
        self._username=username
        self._password=password
        self._baseURL=baseURL
        self._sid=self.update()

    def update(self):
        r = requests.get(self._baseURL+'auth.cgi?api=SYNO.API.Auth&method=Login&version=3&account='+self._username+'&passwd='+self._password+'&session=SurveillanceStation&format=sid',timeout=7)
        res=r.json()
        if res['success'] == False:
            Domoticz.Error('Can not connect to Synology %s:%s: %d'%(self._addr,self._port,res['error']['code']))
            return None
        elif res['success'] == True:
            self._sid='&_sid="'+res['data']['sid']+'"'
            Domoticz.Log("Connected to Synology: %s"%(self._sid))
        return self._sid

    def getSid(self):
        return self._sid
    
class HomeMode:
    def __init__(self,baseURL):
        self._homeMode=True
        self._baseURL=baseURL
        
    def update(self,sid):
        r = requests.get(self._baseURL+'entry.cgi?api="SYNO.SurveillanceStation.HomeMode"&version="1"&method="GetInfo"&need_mobiles=true'+sid.getSid(),timeout=5)
        res=r.json()
        if res['success'] == True:
            hm=res["data"]["on"]
            if(hm != self._homeMode):
                self._homeMode = hm
                if(self._homeMode):
                    Devices[255].Update(nValue=1,sValue="On")
                    Domoticz.Debug("HomeMode is going to: On")
                else:
                    Devices[255].Update(nValue=0,sValue="Off")
                    Domoticz.Debug("HomeMode is going to: Off")
        else:
            Domoticz.Error(str(res))

    def getStatus(self):
        return self._homeMode
        
class SurveillanceStationPlugin:

    def __init__(self):
        self._addr=None
        self._port=None
        self._username=None
        self._password=None
        self._cameras={}
        self._sid=None
        self._baseURL=None
        self._cameraPort=None
        self._httpServConn=None
        self._polling=True
        self._sidRefresh=None
        self._sidElapsedTime=0
        self._homeMode=None
        return

    def onStart(self):
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)
        Domoticz.Log("onStart called")
        DumpConfigToLog()
        self._addr=Parameters["Address"]
        self._port=Parameters["Port"]
        self._username=Parameters["Username"]
        self._password=Parameters["Password"]
        self._cameraPort=Parameters["Mode1"]
        self._sidRefresh=int(Parameters["Mode2"])
        self._baseURL='http://%s:%s/webapi/'%(self._addr,self._port)
        self._sid=SID(self._baseURL, self._username,self._password)
        self._homeMode=HomeMode(self._baseURL)
        if(self._homeMode):
            Domoticz.Status("HomeMode: ok")
        else:
            Domoticz.Error("HomeMode: ko")
            #Create server
        self.httpServerConn = Domoticz.Connection(Name="Server Connection", Transport="TCP/IP", Protocol="HTTP", Port=self._cameraPort)
        self.httpServerConn.Listen()
        if not 255 in Devices:
            Domoticz.Device(Name="HomeMode", Unit=255,TypeName="Switch",Subtype=5,Switchtype=8, Image=9).Create()
        #Search new Cameras
        r = requests.get(self._baseURL+'entry.cgi?version="8"&Privilege=true&api="SYNO.SurveillanceStation.Camera"&method="List"&basic=true&camAppInfo=true'+self._sid.getSid(),timeout=5)
        res=r.json()
        for camInfo in res['data']['cameras']:
            camInfo['dsIp']=self._addr
            cam=Camera(camInfo)
            self._cameras[(cam.getId()+1)]=cam
            if cam.getId()>=254:
                Domoticz.Error("Camera ID for %s >= 254"%(cam.getName()))
                return
            Domoticz.Log("Adding Camera %s"%(cam.getName()))
            if not (cam.getId()+1) in Devices:
                #create camera
                Domoticz.Log("Creating Camera %s %d"%(cam.getName(),cam.getId()))
                Domoticz.Device(Name=cam.getName(), Unit=(cam.getId()+1),TypeName="Switch",Subtype=0,Switchtype=0).Create()
                dbConn=sqlite3.connect(os.getcwd()+'/domoticz.db')
                dbCursor=dbConn.cursor()
                url='/?camId='+str(cam.getId())
                dbCursor.execute("INSERT INTO Cameras (Name,Address,Port,ImageURL) VALUES (\"%s\",\"%s\",%s,\"%s\");"%(cam.getName(),'localhost', self._cameraPort,url))
                dbConn.commit()
                lastId=dbCursor.lastrowid
                dbCursor.execute("INSERT INTO CamerasActiveDevices (CameraRowID,DevSceneRowID,DevSceneType,DevSceneDelay,DevSceneWhen) VALUES (%d,%d,0,0,0);"%(lastId,Devices[(cam.getId()+1)].ID))
                dbConn.commit()
                dbConn.close()
        polling=int(Parameters["Mode5"])
        if polling != 0 and polling<=10:
            Domoticz.Heartbeat(polling)
        else:
            self._polling=False
            polling=10
        pTime=polling*self._sidRefresh
        Domoticz.Log("SID Refresh time is set to %d seconds"%(pTime))
        return

    def _camerasUpdate(self):
        r = requests.get(self._baseURL+'entry.cgi?version="8"&Privilege=true&api="SYNO.SurveillanceStation.Camera"&method="List"&basic=true&camAppInfo=true'+self._sid.getSid(),timeout=5)
        res=r.json()
        for camInfo in res['data']['cameras']:
            Domoticz.Debug("Camera %s is in mode %d"%(camInfo['detailInfo']['camName'],camInfo["status"]))
            cam=self._cameras[(camInfo['id']+1)]
            if camInfo["status"] == 0:
                cam.updateStatus("On")
            else:
                cam.updateStatus("Off")

    def onHeartbeat(self):
        Domoticz.Debug("onHeartbeat called")
        self._sidElapsedTime+=1
        if(self._sidElapsedTime >= self._sidRefresh):
            self._sidElapsedTime=0
            self._sid.update()
        if(self._polling):
            if (self._homeMode):
                self._homeMode.update(self._sid)
            else:
                Domoticz.Error("HomeMode update: KO")    
            #Update Camera Status
            self._camerasUpdate()
                    
    def onDeviceAdded(self):
        Domoticz.Log("Adding device")
        return

    def onStop(self):
        return

    def onConnect(self,Connection, Status, Description):
        Domoticz.Log("onConnect called")
        if (Status == 0):
            Domoticz.Debug("Connected successfully to: "+Connection.Address+":"+Connection.Port)
        else:
            Domoticz.Error("Failed to connect ("+str(Status)+") to: "+Connection.Address+":"+Connection.Port+" with error: "+Description)
        return
        
    def onMessage(self,Connection,Data):
        Domoticz.Debug("onMessage called for connection: "+Connection.Address+":"+Connection.Port)
        # Incoming Requests
        params = urllib.parse.parse_qs(urllib.parse.urlparse(Data["URL"]).query)
        if("camId" not in params or len(params["camId"])==0):
            Connection.Send({"Status":"400 Bad Request", "Headers": {"Connection": "keep-alive", "Accept": "Content-Type: text/html; charset=UTF-8"}, "Data": "Error"})
            Domoticz.Error("No camera Id gived: %s"%Data["URL"])
            return
        Domoticz.Debug(str(params["camId"]))
        camId=int(params["camId"][0])
        cam=self._cameras[(camId+1)]
        data=cam.getSnapShot(self._sid.getSid())
        Connection.Send({"Status":"200 OK", "Headers": {"Connection": "keep-alive", "Accept": "Content-Type: image/jpeg"}, "Data": data})
        return

    def onCommand(self,Unit,Command,Level,Hue):
        if Unit==255:
            if Command == "On":
                value='true'
            else:
                value='false'
            r = requests.get(self._baseURL+'entry.cgi?api="SYNO.SurveillanceStation.HomeMode"&version="1"&method="Switch"&on='+value+self._sid.getSid(),timeout=5)
            res=r.json()
            if res['success'] != True:
                Domoticz.Error("Can not set HomeMode")
                Domoticz.Error(str(res))
            else:
                self._homeMode.update(self._sid)
        else:
            if Command == "Snap":
                Domoticz.Status("Take a snap")
                os.system('/home/pi/tools/Yolo/analyse.sh &')
                return
            elif Command == "Off":
                method="Disable"
            else:
                method="Enable"
            r = requests.get(self._baseURL+'entry.cgi?api="SYNO.SurveillanceStation.Camera"&version="9"&method="'+method+'"&idList='+str(Unit)+self._sid.getSid(),timeout=5)
            res=r.json()
            if res['success'] != True:
                Domoticz.Error("Cant not change camera mode")
                Domoticz.Error(str(res))
            else:
                self._camerasUpdate()

    def onNotification(self,Name,Subject,Text,Status,Priority,Sound,ImageFile):
        return

    def onDisconnect(self,Connection):
        Domoticz.Log("onDisconnect called for connection '"+Connection.Name+"'.")
        return

global _plugin
_plugin = SurveillanceStationPlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

def  onDeviceAdded():
    global _plugin
    _plugin.onDeviceAdded()
    # Generic helper functions

def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
            Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return

