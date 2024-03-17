// Copyright (c) 2018 Maen Artimy
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.


// Main code to handle group tables
$(function () {
    var tabsObj = new Tabs('multicast');

    function displaySnackbar(msg) {
        var $x = $("#snackbar");
        $x.text(msg)
        $x.toggleClass("show");
        setTimeout(function () {
            $x.toggleClass("show");
        }, 3000);
    }


    // Get flows data from swicthes
    function loadGroups() {
        expand_form();
        register_group_add();
        getMulticastGroupData(
            function (src_list) {
                tabsObj.buildTabs("#main2", src_list, "No Multicast groups to show!")
            },
            function (src_list, groups) {
                $.get("/availablenodes")
                    .done(function (data) {
                        let available_dst = data["available_dst"]
                        available_dst.sort(function (a, b) {
                            return a - b;
                        });
                        for (let i in src_list) {
                            let form_id = "group-mod-form-" + src_list[i]
                            let container_id = "checkbox-container-" + src_list[i]
                            let $html_code = $('<form id="' + form_id + '">\n' +
                                '            <fieldset style="margin-bottom: 10px; margin-top: 10px">\n' +
                                '                <legend>Update destination nodes</legend>\n' +
                                '                <div id="' + container_id + '"></div>\n' +
                                '            </fieldset>\n' +
                                '\n' +
                                '            <div class="formcontrol" style="margin-bottom: 10px; margin-top: 10px">\n' +
                                '                <input type="submit" value="Submit">\n' +
                                '                <input type="reset" value="Clear">\n' +
                                '            </div>\n' +
                                '        </form>')
                            tabsObj.buildContent(src_list[i], $html_code)
                            expand_checkbox_container(container_id, available_dst, groups[src_list[i]])
                            register_group_mod(src_list[i], form_id, container_id)
                        }
                        tabsObj.setActive()
                    })
                    .fail(function () {
                        console.log("No Response from server!");
                    });

            });
    }

    function getMulticastGroupData(f, g) {
        $.get("/currentgroups")
            .done(function (groups) {
                // groups: {src: [recv]}

                let src_list = []
                for (let src in groups) {
                    if (groups.hasOwnProperty(src)) {
                        src_list.push(src)
                    }
                }
                f(src_list);
                $.when.apply(this, src_list).then(function () {
                    g(src_list, groups);
                });
            })
            .fail(function () {
                console.log("No Response from server!");
            });
    }

    function expand_form() {
        $.get("/availablenodes")
            .done(function (data) {
                let available_src = data["available_src"]
                let available_dst = data["available_dst"]
                available_src.sort(function (a, b) {
                    return a - b;
                });
                available_dst.sort(function (a, b) {
                    return a - b;
                });
                expand_radio_container("radio-container", available_src)
                expand_checkbox_container("checkbox-container", available_dst, [])
            })
            .fail(function () {
                console.log("No Response from server!");
            });
    }

    function expand_radio_container(id, available_src) {
        // 选择包含单选框的容器元素
        var container = d3.select("#" + id);

        // 为每个数据项创建单选框和标签
        container.selectAll("div")
            .data(available_src)
            .enter()
            .append("div")
            .attr("class", "checkbox-item")
            .html(function (d) {
                return '<input type="radio" id="' + d + '" name=' + id + ' value="' + d + '"><label for="' + d + '">' + d + '</label>';
            });
    }

    function expand_checkbox_container(id, available_dst, chosen) {
        // 选择包含复选框的容器元素
        var container = d3.select("#" + id);

        // 为每个数据项创建复选框和标签
        container.selectAll("div")
            .data(available_dst)
            .enter()
            .append("div")
            .attr("class", "checkbox-item")
            .html(function (d) {
                // 检查当前值是否需要被选中
                var isChecked = chosen.includes(d);
                // 如果需要被选中，则设置 checked 属性
                var checkedAttr = isChecked ? 'checked="checked"' : '';
                return '<input type="checkbox" id="' + d + '" name=' + id + ' value="' + d + '" ' + checkedAttr + '><label for="' + d + '">' + d + '</label>';
            });
    }


    // When the refresh button is clicked, clear the page and start over
    $("[name='refresh']").on('click', function () {
        loadGroups();
    })

    loadGroups();

    function register_group_add() {
        d3.select("#group-add-form")
            .on("submit", function () {
                d3.event.preventDefault();
                var srcData = d3.selectAll("input[name='radio-container']:checked")
                    .nodes()
                    .map(function (node) {
                        return parseInt(node.value);
                    })

                var dstsData = d3.selectAll("input[name='checkbox-container']:checked")
                    .nodes()
                    .map(function (node) {
                        return parseInt(node.value);
                    });

                console.log(srcData);
                console.log(dstsData);

                // 在这里可以将数据提交到后端服务器处理，或者进行其他操作
                if (srcData.length === 1 && dstsData.length !== 0) {
                    const request_body = {"src": srcData[0], "dst": dstsData}
                    $.post("/groupadd", JSON.stringify(request_body))
                        .done(function (response) {
                            displaySnackbar(response)
                            setTimeout(function() {
                                location.reload();
                            }, 1000);
                        })
                        .fail(function () {
                            displaySnackbar("No response from controller.");
                        })
                } else {
                    displaySnackbar("INVALID ARGUMENTS!");
                }
            });
    }


    function register_group_mod(src, form_id, container_id) {
        d3.select("#" + form_id)
            .on("submit", function () {
                d3.event.preventDefault();

                var dstsData = d3.selectAll("input[name='" + container_id + "']:checked")
                    .nodes()
                    .map(function (node) {
                        return parseInt(node.value);
                    });

                console.log(dstsData);

                // 在这里可以将数据提交到后端服务器处理，或者进行其他操作
                if (dstsData.length !== 0) {
                    const request_body = {"src": parseInt(src), "dst": dstsData}
                    $.post("/groupmod", JSON.stringify(request_body))
                        .done(function (response) {
                            displaySnackbar(response)
                            setTimeout(function() {
                                location.reload();
                            }, 1000);
                        })
                        .fail(function () {
                            displaySnackbar("No response from controller.");
                        })
                } else {
                    displaySnackbar("INVALID ARGUMENTS!");
                }
            });

    }


})
