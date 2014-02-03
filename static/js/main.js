// # 1up button behavior
// 
// * Request oneup from Souma
// * Toggle button css state
// * Increase/decrease counter
$(".oneup").click(function() {
    var star_id = $(this).attr("id").substr(6);
    $.post("/s/"+star_id+"/1up", function(data) {
        if ('error_message' in data.meta) {
            alert(data.meta.error_message);
        }
        else {
            $("#oneup-"+star_id).toggleClass("btn-primary");
            $("#oneup-"+star_id).toggleClass("btn-inverse");
            var old_count = parseInt($("#oneup-count-"+star_id).text());
            $("#oneup-count-"+star_id).text(data.meta.oneup_count);
        }
    });
});