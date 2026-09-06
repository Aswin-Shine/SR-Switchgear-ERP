from django.urls import path

from apps.pipeline import api

urlpatterns = [
    path("pipeline/stages", api.stages, name="pipeline-stages"),
    path("board", api.board, name="board"),
    path("job-lines/<uuid:line_id>", api.job_line_detail, name="job-line-detail"),
    path(
        "job-lines/<uuid:line_id>/transitions",
        api.create_transition,
        name="job-line-transitions",
    ),
]
