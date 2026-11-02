from django.urls import path

from blog.views import (
    AdminBlogImageView,
    AdminBlogPostDetailView,
    AdminBlogPostsView,
    BlogDetailView,
    BlogListView,
)

urlpatterns = [
    path("api/blog", BlogListView.as_view(), name="blog_list"),
    path("api/blog/<slug:slug>", BlogDetailView.as_view(), name="blog_detail"),
    path("api/admin/blog/posts", AdminBlogPostsView.as_view(), name="admin_blog_posts"),
    path("api/admin/blog/posts/<uuid:post_id>", AdminBlogPostDetailView.as_view(), name="admin_blog_post"),
    path("api/admin/blog/images", AdminBlogImageView.as_view(), name="admin_blog_images"),
]
