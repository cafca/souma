$(".oneup").click(function() {
    var star_id = $(this).attr("id").substr(6);
    $.post("/s/"+star_id+"/1up", function(data) {
        $("#oneup-"+star_id).toggleClass("btn-primary");
        $("#oneup-"+star_id).toggleClass("btn-inverse");
    });
});