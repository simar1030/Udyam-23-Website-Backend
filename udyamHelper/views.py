from .models import Team, Event, NoticeBoard
from rest_framework.response import Response
from .serializers import EventSerializer, TeamSerializer, NoticeBoardSerializer, CertificateSerializer
from customauth.models import UserAcount
from rest_framework import serializers, generics, permissions, status
from rest_framework import permissions
import shutil
from django.http import HttpResponse
from PIL import ImageDraw, Image, ImageFont
import os
from customauth.models import UserAcount
from customauth.views import (
    populate_googlesheet_with_team_data,
    populate_googlesheet_with_eventTeam_data,
    populate_googlesheet_with_collegteam_data,
)
from googleapiclient.discovery import build
from google.oauth2 import service_account
from decouple import config
import qrcode  
from django.shortcuts import render

from udyamBackend.settings import (
    UDGAMID,
    UDYAMID,
    MASHALID,
    EESID,
    SPREADSHEET_ID,
    SERVICE_ACCOUNT_FILE,
    STATIC_ROOT
)


class InputSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField(required=True)
    college_name = serializers.CharField(required=True)
    year = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=True)


def checks(request):
    try:
        event = Event.objects.get(event=request.data["event"])
        leader = UserAcount.objects.get(email=request.data["leader"])
        member1 = (
            UserAcount.objects.get(email=request.data["member1"])
            if request.data["member1"]
            else None
        )
        member2 = (
            UserAcount.objects.get(email=request.data["member2"])
            if request.data["member2"]
            else None
        )
        event_teams = Team.objects.filter(event=event)
        first_yearites = 0
        second_yearites = 0
        if leader.year == "FIRST":
            first_yearites += 1
        elif leader.year == "SECOND":
            second_yearites += 1
        if member2:
            if member2.year == "FIRST":
                first_yearites += 1
            elif member2.year == "SECOND":
                second_yearites += 1
        if member1:
            if member1.year == "FIRST":
                first_yearites += 1
            elif member1.year == "SECOND":
                second_yearites += 1
    except Event.DoesNotExist:
        return "Event does not exist"
    except UserAcount.DoesNotExist:
        return "User does not exist"

    if (
        request.data["leader"] == request.data["member1"]
        or request.data["leader"] == request.data["member2"]
        or (
            request.data["member1"] == request.data["member2"]
            and request.data["member1"] != ""
        )
    ):
        return "Single user cannot be present twice in the team"
    elif leader != request.user and member1 != request.user and member2 != request.user:
        return "Requesting user must be a member of the team. Cannot create a team which you are not a part of."
    elif Team.objects.filter(teamname=request.data["teamname"], event=event).count():
        return "Team name already taken"
    elif (
        event_teams.filter(leader=leader).count()
        or event_teams.filter(member1=leader).count()
        or event_teams.filter(member2=leader).count()
    ):
        return "Leader already has a team in this event"
    elif (
        event_teams.filter(leader=member1).count()
        or event_teams.filter(member1=member1).count()
        or event_teams.filter(member2=member1).count()
    ) and member1 is not None:
        return "Member 1 already has a team in this event"
    elif (
        event_teams.filter(leader=member2).count()
        or event_teams.filter(member1=member2).count()
        or event_teams.filter(member2=member2).count()
    ) and member2 is not None:
        return "Member 2 already has a team in this event"
    elif (
        second_yearites != 0
        and first_yearites + second_yearites > event.members_after_1st_year
    ):
        return (
            "Max size of a not-all-1st-yearites team is "
            + str(event.members_after_1st_year)
            + " for this event"
        )
    elif second_yearites == 0 and first_yearites > event.members_from_1st_year:
        return (
            "Max size of a all-1st-yearites team is "
            + str(event.members_from_1st_year)
            + " for this event"
        )


class ViewAllEvent(generics.ListAPIView):
    serializer_class = EventSerializer
    queryset = Event.objects.all()


class TeamCreateView(generics.GenericAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = TeamSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = checks(request)
        if message:
            return Response({"error": message}, status=status.HTTP_403_FORBIDDEN)
        serializer.save()
        populate_googlesheet_with_team_data()
        populate_googlesheet_with_eventTeam_data()
        populate_googlesheet_with_collegteam_data()
        team = Team.objects.get(
            teamname=request.data["teamname"],
            event=Event.objects.get(event=request.data["event"]),
        )
        team_info = {
            "teamname": team.teamname,
            "event": team.event.event,
            "leader": team.leader.email,
            "member1": team.member1.email if team.member1 else None,
            "member2": team.member2.email if team.member2 else None,
        }
        return Response(team_info, status=status.HTTP_200_OK)


class TeamCountView(generics.GenericAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = TeamSerializer

    def get(self, request):
        res = {}
        for event in Event.objects.all():
            teams = Team.objects.filter(event=event)
            res[event.event] = teams.count()
        return Response(res, status=status.HTTP_200_OK)


class GetAllNoticeView(generics.RetrieveAPIView):
    serializer_class = NoticeBoardSerializer
    queryset = NoticeBoard.objects.all()

    def get(self, request, event):
        if event == "all":
            eventslist = self.queryset.all()
        else:
            eventslist = self.queryset.filter(event=event)

        context = []
        for event in eventslist:
            context.append(
                {
                    "title": event.title,
                    "description": event.description,
                    "date": event.date,
                    "link": event.link,
                }
            )
        return Response(context, status=status.HTTP_200_OK)


class TeamGetUserView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = TeamSerializer

    def appendTeam(self, teams, event_teams):
        for team in teams:
            team_info = {
                "id": team.id,
                "teamname": team.teamname,
                "event": team.event.event,
                "leader": team.leader.email,
                "member1": team.member1.email if team.member1 else None,
                "member2": team.member2.email if team.member2 else None,
            }
            event_teams.append(team_info)

    def get(self, request):
        try:
            teams_as_leader = Team.objects.filter(leader=request.user)
            teams_as_member1 = Team.objects.filter(member1=request.user)
            teams_as_member2 = Team.objects.filter(member2=request.user)
            event_teams = []
            self.appendTeam(teams_as_leader, event_teams)
            self.appendTeam(teams_as_member1, event_teams)
            self.appendTeam(teams_as_member2, event_teams)
            return Response(event_teams, status=status.HTTP_200_OK)
        except UserAcount.DoesNotExist:
            return Response(
                {"error": "No such user exists"}, status=status.HTTP_404_NOT_FOUND
            )


def checks2(request):
    try:
        event = Event.objects.get(event=request.data["event"])
        leader = UserAcount.objects.get(email=request.data["leader"])
        try:
            teamname = Team.objects.filter(event=event, leader=leader)[0].teamname
        except:
            return "Team Does Not Exist"

        member1 = (
            UserAcount.objects.get(email=request.data["member1"])
            if request.data["member1"]
            else None
        )
        member2 = (
            UserAcount.objects.get(email=request.data["member2"])
            if request.data["member2"]
            else None
        )

        event_teams = Team.objects.filter(event=event)
        first_yearites = 0
        second_yearites = 0
        if leader.year == "FIRST":
            first_yearites += 1
        elif leader.year == "SECOND":
            second_yearites += 1
        if member2:
            if member2.year == "FIRST":
                first_yearites += 1
            elif member2.year == "SECOND":
                second_yearites += 1
        if member1:
            if member1.year == "FIRST":
                first_yearites += 1
            elif member1.year == "SECOND":
                second_yearites += 1
    except Event.DoesNotExist:
        return "Event does not exist"
    except UserAcount.DoesNotExist:
        return "User does not exist"

    if (
        request.data["leader"] == request.data["member1"]
        or request.data["leader"] == request.data["member2"]
        or (
            request.data["member1"] == request.data["member2"]
            and request.data["member1"] != ""
        )
    ):
        return "Single user cannot be present twice in the team"
    elif leader != request.user and member1 != request.user and member2 != request.user:
        return "Requesting user must be a member of the team. Cannot edit a team which you are not a part of."
    elif teamname != request.data["teamname"]:
        if Team.objects.filter(teamname=request.data["teamname"]).count() != 0:
            return "Same Name team already exists."
    elif member1 != None and request.data["member1"] == None:
        return "Member1 Name cannot be an empty string"
    elif member2 != None and request.data["member2"] == None:
        return "Member2 Name cannot be an empty string"
    elif (
        (
            event_teams.filter(leader=member1).count()
            and event_teams.filter(leader=member1)[0].leader != leader
        )
        or (
            event_teams.filter(member1=member1).count()
            and event_teams.filter(member1=member1)[0].leader != leader
        )
        or (
            event_teams.filter(member2=member1).count()
            and event_teams.filter(member2=member1)[0].leader != leader
        )
    ) and member1 is not None:
        return "Member 1 already has a team in this event"
    elif (
        (
            event_teams.filter(leader=member2).count()
            and event_teams.filter(leader=member2)[0].leader != leader
        )
        or (
            event_teams.filter(member1=member2).count()
            and event_teams.filter(member1=member2)[0].leader != leader
        )
        or (
            event_teams.filter(member2=member2).count()
            and event_teams.filter(member2=member2)[0].leader != leader
        )
    ) and member2 is not None:
        return "Member 2 already has a team in this event"
    elif (
        second_yearites != 0
        and first_yearites + second_yearites > event.members_after_1st_year
    ):
        return (
            "Max size of a not-all-1st-yearites team is "
            + str(event.members_after_1st_year)
            + " for this event"
        )
    elif second_yearites == 0 and first_yearites > event.members_from_1st_year:
        return (
            "Max size of a all-1st-yearites team is "
            + str(event.members_from_1st_year)
            + " for this event"
        )


class TeamView(generics.GenericAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = TeamSerializer

    def teamInfo(self, team):
        team_info = {
            "teamname": team.teamname,
            "event": team.event.event,
            "leader": team.leader.email,
            "member1": team.member1.email if team.member1 else None,
            "member2": team.member2.email if team.member2 else None,
        }
        return team_info

    def get(self, request, id):
        try:
            team = Team.objects.get(id=id)
            return Response(self.teamInfo(team), status=status.HTTP_200_OK)
        except Team.DoesNotExist:
            return Response(
                {"error": "Team not found"}, status=status.HTTP_404_NOT_FOUND
            )

    def patch(self, request, id):
        try:
            team = Team.objects.get(id=id)
            event = Event.objects.get(event=request.data["event"])
            leader = UserAcount.objects.get(email=request.data["leader"])
            team.teamname = request.data["teamname"]
            team.event = event
            team.leader = leader
            team.member1 = (
                UserAcount.objects.get(email=request.data["member1"])
                if request.data["member1"] != ""
                else None
            )
            team.member2 = (
                UserAcount.objects.get(email=request.data["member2"])
                if request.data["member2"] != ""
                else None
            )

            message = checks2(request)

            if message and message != "Team name already taken":
                return Response({"error": message}, status=status.HTTP_403_FORBIDDEN)
            team.save()
            populate_googlesheet_with_team_data()
            populate_googlesheet_with_eventTeam_data()
            populate_googlesheet_with_collegteam_data()
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=False)
            team_info = {
                "teamname": team.teamname,
                "event": team.event.event,
                "leader": team.leader.email,
                "member1": team.member1.email if team.member1 else None,
                "member2": team.member2.email if team.member2 else None,
            }
            return Response(team_info, status=status.HTTP_200_OK)
        except Team.DoesNotExist:
            return Response(
                {"error": "Team not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Event.DoesNotExist:
            return Response(
                {"error": "Event not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except UserAcount.DoesNotExist:
            return Response(
                {"error": "User account not found"}, status=status.HTTP_404_NOT_FOUND
            )

    def delete(self, request, id):
        if Team.objects.filter(id=id).count():
            team = Team.objects.get(id=id)
            if request.user == team.leader:
                team.delete()
                return Response(
                    {"message": "Team deleted successfully"}, status=status.HTTP_200_OK
                )
            return Response(
                {"error": "Only a team member is allowed to delete his/her team."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response({"error": "Team not found"}, status=status.HTTP_404_NOT_FOUND)

def getPORS(Email):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    spreadsheet_id = config("SPREADSHEET_ID", default=SPREADSHEET_ID)
    service_account_file = SERVICE_ACCOUNT_FILE
    creds = None
    creds = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=scopes
    )
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()
    ees = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range="EES-PORS!A2:E1000"
    ).execute()
    EES = list(ees.values())[2]
    userfont0 = ImageFont.truetype("{}/Aller_Rg.ttf".format(STATIC_ROOT), 45)
    userfont = ImageFont.truetype("{}/Aller_Rg.ttf".format(STATIC_ROOT), 38)
    userfont1 = ImageFont.truetype("{}/Aller_Rg.ttf".format(STATIC_ROOT), 54)
    count = 0
    for porData in EES:
        name = porData[0]
        email = porData[1]
        designation = porData[2]
        qrtext = "https://ees23.pythonanywhere.com/api/verify/{}".format(porData[3])
        if (email == Email):
            count+=1
            qr = qrcode.QRCode(box_size=5)
            qr.add_data(qrtext)
            qr.make()
            qr_img = qr.make_image()
            img = Image.open("{}/Templates/EES_POR.png".format(STATIC_ROOT))
            img.paste(qr_img,[336,670])
            draw = ImageDraw.Draw(img)
            w, h = draw.textsize(name, font=userfont1)
            image_width = img.width
            W = 840
            H = 1030
            coords = ((image_width - w) / 2, H)
            draw.text(
                xy=coords,
                text="{}".format(name),
                fill=(0, 0, 0),
                font=userfont1,
            )
            draw.text(
                xy=(1180, 1280),
                text="{}".format(designation),
                fill=(0, 0, 0),
                font=userfont0,
            )
            img.save(
                "{}/certificates/{}_{}.png".format(
                    STATIC_ROOT,designation, name
                )
            )
    return count


def createCerti(Email):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    spreadsheet_id = config("SPREADSHEET_ID", default=SPREADSHEET_ID)
    service_account_file = SERVICE_ACCOUNT_FILE
    creds = None
    creds = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=scopes
    )
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()
    udyam = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range="UDYAM-CERTIFICATES!A2:E1000"
    ).execute()
    Udyam = list(udyam.values())[2]
    udgam = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range="UDGAM-CERTIFICATES!A2:E1000"
    ).execute()
    Udgam = list(udgam.values())[2]
    mashal = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range="MASHAL-CERTIFICATES!A2:E1000"
    ).execute()
    Mashal = list(mashal.values())[2]

    Events = {}
    Events["Udyam"] = Udyam
    Events["Udgam"] = Udgam
    Events["Mashal"] = Mashal
    userfont0 = ImageFont.truetype("{}/Aller_Rg.ttf".format(STATIC_ROOT), 45)
    userfont = ImageFont.truetype("{}/Aller_Rg.ttf".format(STATIC_ROOT), 38)
    userfont1 = ImageFont.truetype("{}/Aller_Rg.ttf".format(STATIC_ROOT), 54)
    os.makedirs("{}/certificates".format(STATIC_ROOT))
    count=0
    for key, data_values in Events.items():
        for data in data_values:
            name = data[0]
            email = data[1]
            pos = data[2]
            event = data[3]
            qrtext = "https://ees23.pythonanywhere.com/api/verify/{}".format(data[4])
            if (email == Email):
                count+=1
                qr = qrcode.QRCode(box_size=5)
                qr.add_data(qrtext)
                qr.make()
                qr_img = qr.make_image()
                if (pos != ""):
                    img = Image.open("{}/Templates/{}_Winner.png".format(STATIC_ROOT,key))
                    img.paste(qr_img,[336,670])
                    draw = ImageDraw.Draw(img)
                    w, h = draw.textsize(name, font=userfont1)
                    image_width = img.width
                    W = 840
                    H = 1030
                    coords = ((image_width - w) / 2, H)
                    draw.text(
                        xy=coords,
                        text="{}".format(name),
                        fill=(0, 0, 0),
                        font=userfont1,
                    )
                    draw.text(
                        xy=(1097, 1148),
                        text="{}".format(pos),
                        fill=(0, 0, 0),
                        font=userfont0,
                    )
                    draw.text(
                        xy=(1470, 1150),
                        text="{}".format(event),
                        fill=(0, 0, 0),
                        font=userfont0,
                    )
                    img.save(
                        "{}/certificates/{}_{}.png".format(
                            STATIC_ROOT,event, name
                        )
                    )
                else:
                    img = Image.open("{}/Templates/{}_Participation.png".format(STATIC_ROOT,key))
                    img.paste(qr_img,[336,670])
                    draw = ImageDraw.Draw(img)
                    w, h = draw.textsize(name, font=userfont1)
                    image_width = img.width
                    W = 840
                    H = 1030
                    coords = ((image_width - w) / 2, H)
                    draw.text(
                        xy=coords,
                        text="{}".format(name),
                        fill=(0, 0, 0),
                        font=userfont1,
                    )
                    draw.text(
                        xy=(1480, 1150),
                        text="{}".format(event),
                        fill=(0, 0, 0),
                        font=userfont0,
                    )
                    img.save(
                        "{}/certificates/{}_{}.png".format(
                            STATIC_ROOT,event, name
                        )
                    )
    count+=getPORS(Email)
    file1 = open("{}/certificates/readme.txt".format(STATIC_ROOT), "a")
    L = [
        "You've got {} certificate from the Electronics Engineering Society.\n".format(count),
        "This zip incorporates the certificates from all the events of Udyam, Udgam, and Mashal!\n\n",
        "Please note that details of all the participants who qualified for certificates are given by event coordinators. For any inconsistency try reaching them. "
        ]
    file1.writelines(L)
    file1.close()
    shutil.make_archive("{}/certificates".format(STATIC_ROOT), "zip", "{}/certificates".format(STATIC_ROOT))
    zip_file = open("{}/certificates.zip".format(STATIC_ROOT), "rb")
    return zip_file

class CertificateGetUserView(generics.GenericAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = CertificateSerializer

    def get(self, request):
        print(request.user.email)
        try:
            zip_file = createCerti(request.user.email)
            response = HttpResponse(zip_file, content_type="application/zip")
            response["Content-Disposition"] = (
                'attachment; filename="%s"' % "certificates.zip"
            )
            os.remove("{}/certificates.zip".format(STATIC_ROOT))
            shutil.rmtree("{}/certificates".format(STATIC_ROOT))
            return response
        except:
            if os.path.exists("{}/certificates".format(STATIC_ROOT)):
                shutil.rmtree("{}/certificates".format(STATIC_ROOT))
                try:
                    os.remove("{}/certificates.zip".format(STATIC_ROOT))
                except:
                    return Response({"error": "Unknown Error Occurred"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"error": "Please Try Again"}, status=status.HTTP_404_NOT_FOUND)


def CertificateVerify(request, id):
    if request.method == "GET":
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        spreadsheet_id = config("SPREADSHEET_ID", default=SPREADSHEET_ID)
        service_account_file = SERVICE_ACCOUNT_FILE
        creds = None
        creds = service_account.Credentials.from_service_account_file(
            service_account_file, scopes=scopes
        )
        service = build("sheets", "v4", credentials=creds)
        sheet = service.spreadsheets()
        ids = [UDYAMID, UDGAMID, MASHALID]
        events = ["UDYAM", "UDGAM", "MASHAL"]
        for i in range(3):
            if id[:6] == ids[i]:
                data = sheet.values().get(
                    spreadsheetId=spreadsheet_id,
                    range="{}-CERTIFICATES!A2:E1000".format(events[i])
                ).execute()
                Data = list(data.values())[2]
                for data in Data:
                    name = data[0]
                    pos = data[2]
                    event = data[3]
                    userid = data[4]
                    if userid == id:
                        content = "This certificate is proudly presented to {} for ".format(name)
                        content += ("participating in " if pos=="" else " securing {} position in ".format(pos))
                        content += "{} held under {}'23, EES IIT BHU!".format(event, events[i])
                        return render(request, "verify.html", {"bg": "success", "content": content})
        # Verify POR
        print(EESID)
        if id[:7] == EESID:
            data = sheet.values().get(
                spreadsheetId=spreadsheet_id,
                range="EES-PORS!A2:E1000"
            ).execute()
            Data = list(data.values())[2]
            for data in Data:
                name = data[0]
                designation = data[2]
                userid = data[3]
                if userid == id:
                    content = "This certificate is proudly presented to {} for ".format(name)
                    content += ("successfully organizing EES Fest '23 held by Electronics Engineering Society ")
                    content += "from 7th-9th April, 2023 in the capacity of {}.".format(designation)
                    return render(request, "verify.html", {"bg": "success", "content": content})
        return render(request, "verify.html", {"bg": "danger", "content": "Invalid Certificate!"})
    return render(request, "verify.html", {"bg": "danger", "content": "Invalid Request!"})