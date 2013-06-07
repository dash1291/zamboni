from django.contrib.auth.models import AnonymousUser
from django.db.models import Q

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer
from rest_framework.viewsets import ModelViewSet

from access import acl
from comm.models import (CommunicationNote, CommunicationThread,
                         CommunicationThreadCC)
from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)


class NoteSerializer(ModelSerializer):
    class Meta:
        model = CommunicationNote
        fields = ('author', 'body',)
        exclude = ('thread',)


class ThreadSerializer(ModelSerializer):
    notes = NoteSerializer()

    class Meta:
        model = CommunicationThread
        fields = ('id', 'addon', 'version', 'notes',)
        view_name = 'comm-thread-detail'


class ThreadPermission(BasePermission):
    """Permission wrapper for checking if the authenticated user has the
    permission to view the thread."""
    
    def check_acls(self, acl_type):
        request = self.request
        if acl_type == 'moz_contact':
            return request.user.email == self.obj.addon.mozilla_contact
        elif acl_type == 'admin':
            return acl.action_allowed(request, 'Admin', '%')
        elif acl_type == 'reviewer':
            return acl.action_allowed(request, 'App', 'Review')
        elif acl_type == 'senior_reviewer':
            return acl.action_allowed(request, 'Apps', 'ReviewEscalated')
        else:
            raise 'Invalid ACL lookup.'

    def has_object_permission(self, request, view, obj):
        if isinstance(request.user, AnonymousUser) or (
            obj.read_permission_public):
            return obj.read_permission_public

        # consider thread CCs
        # consider thread permissions
        self.request = request
        self.obj = obj
        user = request.user.get_profile()

        n = CommunicationNote.objects.filter(author=user, thread=obj)
        cc = CommunicationThreadCC.objects.filter(user=user, thread=obj)
        if n.exists() or cc.exists():
            return True

        if ((obj.read_permission_developer and user.is_developer) or (
            obj.read_permission_reviewer and self.check_acls('reviewer')) or (
            obj.read_permission_senior_reviewer and self.check_acls(
                'senior_reviewer')) or (
            obj.read_permission_mozilla_contact and self.check_acls(
                'moz_contact')) or (
            obj.read_permission_staff and self.check_acls('admin'))):
            return True

        return False


class ThreadViewSet(ModelViewSet):
    serializer_class = ThreadSerializer
    queryset = CommunicationThread.objects.all()
    authentication_classes = (RestSharedSecretAuthentication,
                              RestOAuthAuthentication,)
    permission_classes = (ThreadPermission,)

    def list(self, request):
        profile = request.user.get_profile()
        notes = profile.comm_notes.values_list('thread')
        cc = profile.comm_thread_cc.values_list('thread')

        queryset = CommunicationThread.objects.filter(Q(pk__in=notes) | (
            Q(pk__in=cc)))

        r = [ThreadSerializer(t).data for t in queryset]
        return Response(r)
