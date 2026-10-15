from django.urls import path

from .views import analysis, comments, commitments, reviews

app_name = "reviews"

urlpatterns = [
    path("reviews/", reviews.review_list, name="list"),
    path("reviews/new/", reviews.review_new, name="new"),
    path("reviews/<str:code>/", reviews.review_edit, name="edit"),
    path("reviews/<str:code>/save/", reviews.review_save, name="save"),
    path("reviews/<str:code>/acknowledge/", reviews.review_acknowledge, name="acknowledge"),
    path("reviews/<str:code>/status/", reviews.review_status, name="status"),
    path("reviews/<str:code>/present/", reviews.review_present, name="present"),
    path("reviews/<str:code>/pdf/", reviews.review_pdf, name="pdf"),
    path("reviews/<str:code>/revisions/<int:number>/", reviews.revision_detail, name="revision"),
    path("reviews/<str:code>/comments/add/", comments.comment_add, name="comment_add"),
    path("comments/", comments.comment_list, name="comments"),
    path("comments/<int:pk>/edit/", comments.comment_edit, name="comment_edit"),
    path("comments/<int:pk>/delete/", comments.comment_delete, name="comment_delete"),
    path("commitments/", commitments.tracker, name="commitments"),
    path("commitments/<int:pk>/", commitments.commitment_detail, name="commitment_detail"),
    path("commitments/<int:pk>/update/", commitments.commitment_update, name="commitment_update"),
    path("history/", analysis.history, name="history"),
    path("history/compare/", analysis.compare_view, name="compare"),
    path("trends/", analysis.trends_view, name="trends"),
    path("trends/data.json", analysis.trends_data, name="trends_data"),
]
